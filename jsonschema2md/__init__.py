"""Convert JSON Schema to Markdown documentation."""

__author__ = "Stéphane Brunner"
__email__ = "stephane.brunner@gmail.com"
__license__ = "Apache-2.0"


try:
    from importlib.metadata import version
except ImportError:
    from importlib_metadata import version

import argparse
import io
import json
import os
import re
import subprocess  # nosec
import sys
from collections.abc import Sequence
from typing import Optional, Union
from urllib.parse import quote

import mdformat
import yaml

__version__ = version("jsonschema2md")


class Parser:
    """
    JSON Schema to Markdown parser.

    Examples
    --------
    >>> import jsonschema2md
    >>> parser = jsonschema2md.Parser()
    >>> md_lines = parser.parse_schema(json.load(input_json))
    """

    tab_size = 2

    def __init__(self, examples_as_yaml: bool = False, show_examples: str = "all"):
        """
        Setup JSON Schema to Markdown parser.

        Parameters
        ----------
        examples_as_yaml : bool, default False
            Parse examples in YAML-format instead of JSON.
        show_examples: str, default 'all'
            Parse examples for only objects, only properties or all. Valid options are
            `{"all", "object", "properties"}`.

        """
        self.examples_as_yaml = examples_as_yaml

        valid_show_examples_options = ["all", "object", "properties"]
        show_examples = show_examples.lower()
        if show_examples in valid_show_examples_options:
            self.show_examples = show_examples
        else:
            raise ValueError(
                f"`show_examples` option should be one of "
                f"`{valid_show_examples_options}`; `{show_examples}` was passed."
            )

    def _construct_description_line(
        self, obj: dict, add_type: bool = False
    ) -> Sequence[str]:
        """Construct description line of property, definition, or item."""
        description_line = []

        if "description" in obj:
            ending = "" if re.search(r"[.?!;]$", obj["description"]) else "."
            description_line.append(f"{obj['description']}{ending}")
        if add_type:
            if "type" in obj:
                description_line.append(f"Must be of type *{obj['type']}*.")
        if "minimum" in obj:
            description_line.append(f"Minimum: `{obj['minimum']}`.")
        if "exclusiveMinimum" in obj:
            description_line.append(f"Exclusive minimum: `{obj['exclusiveMinimum']}`.")
        if "maximum" in obj:
            description_line.append(f"Maximum: `{obj['maximum']}`.")
        if "exclusiveMaximum" in obj:
            description_line.append(f"Exclusive maximum: `{obj['exclusiveMaximum']}`.")
        if "minItems" in obj or "maxItems" in obj:
            length_description = "Length must be "
            if "minItems" in obj and "maxItems" not in obj:
                length_description += f"at least {obj['minItems']}."
            elif "maxItems" in obj and "minItems" not in obj:
                length_description += f"at most {obj['maxItems']}."
            elif obj["minItems"] == obj["maxItems"]:
                length_description += f"equal to {obj['minItems']}."
            else:
                length_description += (
                    f"between {obj['minItems']} and {obj['maxItems']} (inclusive)."
                )
            description_line.append(length_description)
        if "enum" in obj:
            description_line.append(f"Must be one of: `{json.dumps(obj['enum'])}`.")
        if "const" in obj:
            description_line.append(f"Must be: `{json.dumps(obj['const'])}`.")
        for extra_props in ["additional", "unevaluated"]:
            if f"{extra_props}Properties" in obj:
                if obj[f"{extra_props}Properties"]:
                    description_line.append(f"Can contain {extra_props} properties.")
                else:
                    description_line.append(f"Cannot contain {extra_props} properties.")
        if "$ref" in obj:
            dest = obj["$ref"]
            if dest.endswith(".json"):
                dest = dest[:-5]
            title = os.path.basename(dest)
            description_line.append(f"Includes all of *[{title}]({quote(dest)}.md)*.")
        if "default" in obj:
            description_line.append(f"Default: `{json.dumps(obj['default'])}`.")

        # Only add start colon if items were added
        # if description_line:
        #     description_line.insert(0, ":")

        return description_line

    def _construct_examples(
        self, obj: dict, indent_level: int = 0, add_header: bool = True
    ) -> Sequence[str]:
        def dump_json_with_line_head(obj, line_head, **kwargs):
            result = [
                line_head + line
                for line in io.StringIO(json.dumps(obj, **kwargs)).readlines()
            ]
            return "".join(result)

        def dump_yaml_with_line_head(obj, line_head, **kwargs):
            result = [
                line_head + line
                for line in io.StringIO(
                    yaml.dump(obj, sort_keys=False, **kwargs)
                ).readlines()
            ]
            return "".join(result).rstrip()

        example_lines = []
        if "examples" in obj:
            example_indentation = " " * self.tab_size * indent_level
            if add_header:
                example_lines.append(f"\n{example_indentation}Examples:\n")
            for example in obj["examples"]:
                if self.examples_as_yaml:
                    lang = "yaml"
                    dump_fn = dump_yaml_with_line_head
                else:
                    lang = "json"
                    dump_fn = dump_json_with_line_head
                example_str = dump_fn(example, line_head=example_indentation, indent=4)
                example_lines.append(
                    f"{example_indentation}```{lang}\n{example_str}\n{example_indentation}```\n\n"
                )
        return example_lines

    def append_line(self, line: str, new_lines: list[str]):
        if new_lines:
            last_indent = len(new_lines[-1]) - len(new_lines[-1].lstrip())
            indentation = len(line) - len(line.lstrip())
            if last_indent != indentation and not new_lines[-1].lstrip()[:2] not in [
                "- ",
                "* ",
            ]:
                new_lines.append("\n")
        new_lines.append(line)

    def _parse_object(
        self,
        obj: Union[dict, list],
        name: Optional[str],
        name_monospace: bool = True,
        parsed_lines: Optional[list[str]] = None,
        indent_level: int = 0,
        path: Optional[list[str]] = None,
        required: bool = False,
    ) -> list[str]:
        """Parse JSON object and its items, definitions, and properties recursively."""

        if not parsed_lines:
            parsed_lines = []

        indentation = " " * self.tab_size * indent_level
        indentation_items = " " * self.tab_size * (indent_level + 1)

        if isinstance(obj, list):
            self.append_line(f"{indentation}- **{name}**:\n", parsed_lines)

            for element in obj:
                parsed_lines = self._parse_object(
                    element,
                    None,
                    name_monospace=False,
                    parsed_lines=parsed_lines,
                    indent_level=indent_level + 1,
                )
            return parsed_lines

        if not isinstance(obj, dict):
            raise TypeError(
                f"Non-object type found in properties list: `{name}: {obj}`."
            )

        # Construct full description line
        description_line_base = self._construct_description_line(obj)
        description_line_list = list(
            map(
                lambda line: line.replace("\n\n", "<br>" + indentation_items),
                description_line_base,
            )
        )

        # Add full line to output
        description_line = " ".join(description_line_list)
        optional_format = f", format: {obj['format']}" if "format" in obj else ""
        if name is None:
            obj_type = f"*{obj['type']}{optional_format}*" if "type" in obj else ""
            name_formatted = ""
        else:
            required_str = ", required" if required else ""
            obj_type = (
                f" *({obj['type']}{optional_format}{required_str})*"
                if "type" in obj
                else ""
            )
            name_formatted = f"**`{name}`**" if name_monospace else f"**{name}**"
        anchor = f'<a id="{quote("/".join(path))}"></a>' if path else ""
        self.append_line(
            f"{indentation}- {anchor}{name_formatted}{obj_type}{description_line}\n",
            parsed_lines,
        )

        # Recursively parse subschemas following schema composition keywords
        schema_composition_keyword_map = {
            "allOf": "All of",
            "anyOf": "Any of",
            "oneOf": "One of",
        }
        for key, label in schema_composition_keyword_map.items():
            if key in obj:
                self.append_line(
                    f"{indentation_items}- **{label}**\n",
                    parsed_lines,
                )
                for child_obj in obj[key]:
                    parsed_lines = self._parse_object(
                        child_obj,
                        None,
                        name_monospace=False,
                        parsed_lines=parsed_lines,
                        indent_level=indent_level + 2,
                    )

        # Recursively add items and definitions
        for property_name in ["items", "definitions", "$defs"]:
            if property_name in obj:
                parsed_lines = self._parse_object(
                    obj[property_name],
                    property_name.capitalize(),
                    name_monospace=False,
                    parsed_lines=parsed_lines,
                    indent_level=indent_level + 1,
                )

        # Recursively add additional child properties
        for extra_props in ["additional", "unevaluated"]:
            property_name = f"{extra_props}Properties"
            if property_name in obj and isinstance(obj[property_name], dict):
                parsed_lines = self._parse_object(
                    obj[property_name],
                    f"{extra_props.capitalize()} properties",
                    name_monospace=False,
                    parsed_lines=parsed_lines,
                    indent_level=indent_level + 1,
                )

        # Recursively add child properties
        for property_name in ["properties", "patternProperties"]:
            if property_name in obj:
                for property_name, property_obj in obj[property_name].items():
                    parsed_lines = self._parse_object(
                        property_obj,
                        property_name,
                        parsed_lines=parsed_lines,
                        indent_level=indent_level + 1,
                        required=property_name in obj.get("required", []),
                    )

        # Add examples
        if self.show_examples in ["all", "properties"]:
            parsed_lines.extend(
                self._construct_examples(obj, indent_level=indent_level)
            )

        return parsed_lines

    def parse_schema(self, schema_object_master: dict) -> Sequence[str]:
        """Parse JSON Schema object to markdown text."""

        def gather_props(obj: dict, prop: str) -> list[dict]:
            """Gather properties from schema object and allOf's."""
            res = []

            if prop in obj:
                res.append(obj[prop])
            if "allOf" in obj:
                for sub_obj in obj["allOf"]:
                    res.extend(gather_props(sub_obj, prop))
            return res

        output_lines = []

        # Add title and description
        if "title" in schema_object_master:
            output_lines.append(f"# {schema_object_master['title']}\n\n")
        else:
            output_lines.append("# JSON Schema\n\n")

        if "description" in schema_object_master:
            output_lines.append(f"*{schema_object_master['description']}*\n\n")

        # Add items
        first = False
        for schema_object in gather_props(schema_object_master, "items"):
            if not first:
                output_lines.append("## Items\n\n")
                first = True
            new_lines = self._parse_object(schema_object, "Items", name_monospace=False)
            output_lines.extend(new_lines)

        # Add additional/unevaluated properties
        for extra_props in ["additional", "unevaluated"]:
            property_name = f"{extra_props}Properties"
            title_ = f"{extra_props.capitalize()} Properties"
            if property_name in schema_object_master and isinstance(
                schema_object_master[property_name], dict
            ):
                output_lines.append(f"## {title_}\n\n")
                new_lines = self._parse_object(
                    schema_object_master[property_name],
                    title_,
                    name_monospace=False,
                )
                output_lines.extend(new_lines)

        # Add pattern properties
        first = False
        for schema_object in gather_props(schema_object_master, "patternProperties"):
            if not first:
                output_lines.append("## Pattern Properties\n\n")
                first = True
            for obj_name, obj in schema_object.items():
                new_lines = self._parse_object(obj, obj_name)
                output_lines.extend(new_lines)

        # Add properties
        first = True
        for schema_object in gather_props(schema_object_master, "properties"):
            if first:
                output_lines.append("## Properties\n\n")
                first = False
            for obj_name, obj in schema_object.items():
                required = obj_name in schema_object.get("required", [])
                new_lines = self._parse_object(obj, obj_name, required=required)
                output_lines.extend(new_lines)

        # Add definitions / $defs
        for name in ["definitions", "$defs"]:
            if name in schema_object_master:
                for obj_name, obj in schema_object_master[name].items():
                    new_lines = self._parse_object(obj, obj_name, path=[name, obj_name])
                    output_lines.extend(new_lines)

        # Add examples
        if "examples" in schema_object_master and self.show_examples in [
            "all",
            "object",
        ]:
            output_lines.append("## Examples\n\n")
            new_lines = self._construct_examples(
                schema_object_master, indent_level=0, add_header=False
            )
            output_lines.extend(new_lines)

        return output_lines


def main():
    """Convert JSON Schema to Markdown documentation."""

    argparser = argparse.ArgumentParser(
        "Convert JSON Schema to Markdown documentation."
    )
    argparser.add_argument(
        "--version", action="store_true", help="Show version and exit."
    )
    argparser.add_argument(
        "--pre-commit",
        action="store_true",
        help="Run as pre-commit hook after the generation.",
    )
    argparser.add_argument(
        "--examples-as-yaml",
        action="store_true",
        help="Parse examples in YAML-format instead of JSON.",
    )
    argparser.add_argument(
        "--show-examples",
        choices=["all", "properties", "object"],
        default="object",
        help="Parse examples for only the main object, only properties, or all.",
    )
    argparser.add_argument("input_json", help="Input JSON file.")
    argparser.add_argument("output_markdown", help="Output Markdown file.")

    args = argparser.parse_args()

    if args.version:
        print(__version__)
        sys.exit(0)

    parser = Parser(
        examples_as_yaml=args.examples_as_yaml, show_examples=args.show_examples
    )
    with open(args.input_json, encoding="utf-8") as input_json:
        output_md = parser.parse_schema(json.load(input_json))

    with open(args.output_markdown, "w", encoding="utf-8") as output_markdown:
        text = "\n".join(output_md)
        markdown = mdformat.text(text)
        output_markdown.write(markdown)

    if args.pre_commit:
        subprocess.run(  # pylint: disable=subprocess-run-check # nosec
            ["pre-commit", "run", "--color=never", f"--files={args.output_markdown}"]
        )


if __name__ == "__main__":
    main()

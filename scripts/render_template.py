#!/usr/bin/env python3
"""
Render Jinja2 templates in IQE YAML files.

This script renders template variables in IQE YAML files to make them usable by nise.
"""

import sys
import os
from datetime import datetime
from pathlib import Path
from jinja2 import Template


def render_ocp_template(template_file: str, output_file: str) -> None:
    """
    Render an OCP template YAML file.

    Args:
        template_file: Path to the template YAML file
        output_file: Path to write the rendered YAML file
    """
    # Read template
    with open(template_file, 'r') as f:
        template_content = f.read()

    # Define template variables (matching IQE's ocp_fixtures.py)
    today = datetime.now().strftime('%Y-%m-%d')
    template_vars = {
        'echo_orig_end': f'{today}T00 +0000',
        # Add more variables as needed for other templates
    }

    # Render template
    template = Template(template_content)
    rendered_content = template.render(**template_vars)

    # Write rendered file
    with open(output_file, 'w') as f:
        f.write(rendered_content)

    print(f"✓ Rendered template: {template_file}")
    print(f"  Output: {output_file}")
    print(f"  Variables: {template_vars}")


def main():
    if len(sys.argv) < 3:
        print("Usage: python3 render_template.py <template_file> <output_file>")
        sys.exit(1)

    template_file = sys.argv[1]
    output_file = sys.argv[2]

    if not os.path.exists(template_file):
        print(f"Error: Template file not found: {template_file}")
        sys.exit(1)

    render_ocp_template(template_file, output_file)


if __name__ == "__main__":
    main()


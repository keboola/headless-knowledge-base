"""Handler for Confluence macros in HTML content."""

import re
from dataclasses import dataclass

from bs4 import BeautifulSoup, Tag


@dataclass
class ProcessedMacro:
    """Result of processing a Confluence macro."""

    content: str
    macro_type: str
    should_include: bool = True
    prefix: str = ""


class MacroHandler:
    """Handles Confluence macros in HTML content."""

    # Macros to skip entirely
    SKIP_MACROS = {"toc", "children", "pagetree", "recently-updated"}

    # Info-type macros that add a prefix
    INFO_MACROS = {
        "info": "Info: ",
        "warning": "Warning: ",
        "note": "Note: ",
        "tip": "Tip: ",
    }

    def process_html(self, soup: BeautifulSoup) -> BeautifulSoup:
        """Process all macros in the HTML and modify in place."""
        # Process Confluence macro elements
        self._process_ac_macros(soup)
        self._process_structured_macros(soup)
        return soup

    def _process_ac_macros(self, soup: BeautifulSoup) -> None:
        """Process ac:macro elements (Confluence Cloud format)."""
        for macro in soup.find_all("ac:structured-macro"):
            macro_name = macro.get("ac:name", "").lower()
            result = self._handle_macro(macro, macro_name)

            if not result.should_include:
                macro.decompose()
            else:
                # Replace macro with processed content
                new_content = soup.new_tag("div")
                new_content["class"] = f"macro-{macro_name}"
                if result.prefix:
                    prefix_tag = soup.new_tag("strong")
                    prefix_tag.string = result.prefix
                    new_content.append(prefix_tag)
                # Add the inner content
                if result.content:
                    new_content.append(BeautifulSoup(result.content, "lxml"))
                macro.replace_with(new_content)

    def _process_structured_macros(self, soup: BeautifulSoup) -> None:
        """Process data-macro elements (Confluence storage format)."""
        for macro in soup.find_all(attrs={"data-macro-name": True}):
            macro_name = macro.get("data-macro-name", "").lower()
            result = self._handle_macro(macro, macro_name)

            if not result.should_include:
                macro.decompose()
            else:
                # Keep content but add prefix if needed
                if result.prefix:
                    prefix_tag = soup.new_tag("strong")
                    prefix_tag.string = result.prefix
                    macro.insert(0, prefix_tag)

    def _handle_macro(self, macro: Tag, macro_name: str) -> ProcessedMacro:
        """Handle a specific macro type."""
        # Skip navigational macros
        if macro_name in self.SKIP_MACROS:
            return ProcessedMacro(content="", macro_type=macro_name, should_include=False)

        # Info-type macros
        if macro_name in self.INFO_MACROS:
            content = self._extract_macro_body(macro)
            return ProcessedMacro(
                content=content,
                macro_type=macro_name,
                prefix=self.INFO_MACROS[macro_name],
            )

        # Code blocks
        if macro_name == "code":
            content = self._extract_code_content(macro)
            return ProcessedMacro(content=content, macro_type="code")

        # Expand/collapse sections
        if macro_name == "expand":
            content = self._extract_macro_body(macro)
            return ProcessedMacro(content=content, macro_type="expand")

        # Panel sections
        if macro_name == "panel":
            content = self._extract_macro_body(macro)
            return ProcessedMacro(content=content, macro_type="panel")

        # Excerpt - mark as summary candidate
        if macro_name == "excerpt":
            content = self._extract_macro_body(macro)
            return ProcessedMacro(content=content, macro_type="excerpt")

        # Default: include content
        content = self._extract_macro_body(macro)
        return ProcessedMacro(content=content, macro_type=macro_name)

    def _extract_macro_body(self, macro: Tag) -> str:
        """Extract the body content from a macro."""
        # Try ac:rich-text-body first (Confluence Cloud)
        body = macro.find("ac:rich-text-body")
        if body:
            return str(body)

        # Try ac:plain-text-body
        body = macro.find("ac:plain-text-body")
        if body:
            return body.get_text()

        # Try data-macro-body
        body_attr = macro.get("data-macro-body")
        if body_attr:
            return str(body_attr)

        # Return inner HTML
        return str(macro)

    def _extract_code_content(self, macro: Tag) -> str:
        """Extract code block content, preserving formatting."""
        # Try to find plain text body
        body = macro.find("ac:plain-text-body")
        if body:
            # Decode CDATA if present
            text = body.get_text()
            return f"```\n{text}\n```"

        # Try pre tag
        pre = macro.find("pre")
        if pre:
            return f"```\n{pre.get_text()}\n```"

        return "```\n" + macro.get_text() + "\n```"


def clean_confluence_html(html: str) -> str:
    """
    Clean Confluence-specific HTML elements and attributes.

    This removes:
    - Confluence-specific namespaced tags that are empty
    - Data attributes used for editing
    - Style attributes
    """
    # Remove empty ac: tags
    html = re.sub(r"<ac:[^>]*>\s*</ac:[^>]*>", "", html)

    # Remove ri: tags (resource identifiers)
    html = re.sub(r"<ri:[^>]*/>", "", html)
    html = re.sub(r"<ri:[^>]*>.*?</ri:[^>]*>", "", html, flags=re.DOTALL)

    return html

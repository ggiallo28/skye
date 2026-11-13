"""Unit tests for BasePromptBuilder."""

# Import test data from the proper location
import json
import sys
from pathlib import Path

import pytest

from skye.base.exceptions import ValidationError
from skye.base.messages import UserMessage
from skye.prompts import BasePromptBuilder

test_data_path = Path(__file__).parent / "test_data"
sys.path.insert(0, str(test_data_path.parent))

try:
    from test_data import load_classification_examples, load_ner_examples
except ImportError:
    # Fallback if import fails
    def load_ner_examples():
        return [{"text": "Apple Inc.", "entities": [{"text": "Apple Inc.", "label": "ORG"}]}]

    def load_classification_examples():
        return [{"text": "Great!", "category": "positive"}]


class TestBasePromptBuilder:
    """Test cases for BasePromptBuilder."""

    def test_initialization(self):
        """Test builder initializes with templates loaded from files."""
        builder = BasePromptBuilder()

        # Should have templates loaded from the templates folder
        template_names = [key.split(":")[0] for key in builder._templates.keys()]

        # Check that some templates are loaded (the exact names depend on what's in templates folder)
        assert len(template_names) > 0

        # Check that common templates exist (these should be in the templates folder)
        expected_templates = ["extraction_entities", "text_classification", "text_summarization", "text_question_answering"]
        found_templates = [
            name
            for name in expected_templates
            if any(name in key for key in builder._templates.keys())
        ]
        assert (
            len(found_templates) > 0
        ), f"Expected some of {expected_templates}, found templates: {template_names}"

    def test_register_and_get_template(self):
        """Test template registration and retrieval."""
        builder = BasePromptBuilder()

        # Register template
        builder.register_template("test", "Hello {name}!")

        # Get template
        template = builder.get_template("test")
        assert template == "Hello {name}!"

        # Get with version
        template = builder.get_template("test", "1.0")
        assert template == "Hello {name}!"

    def test_template_versioning(self):
        """Test template versioning."""
        builder = BasePromptBuilder()

        # Register multiple versions
        builder.register_template("test", "Version 1", "1.0")
        builder.register_template("test", "Version 2", "2.0")

        # Get specific versions
        assert builder.get_template("test", "1.0") == "Version 1"
        assert builder.get_template("test", "2.0") == "Version 2"

        # Get latest (should be 2.0)
        assert builder.get_template("test") == "Version 2"

    def test_render_basic(self):
        """Test basic template rendering."""
        builder = BasePromptBuilder()

        builder.register_template("greeting", "Hello {name}!")
        messages = builder.render("greeting", {"name": "Alice"})

        assert len(messages) == 1
        assert isinstance(messages[0], UserMessage)
        assert messages[0].content == "Hello Alice!"

    def test_render_with_defaults(self):
        """Test rendering with default values."""
        builder = BasePromptBuilder()

        builder.register_template("greeting", "Hello {name} from {location}!")
        builder.set_default_values({"location": "Earth"})

        messages = builder.render("greeting", {"name": "Bob"})
        assert messages[0].content == "Hello Bob from Earth!"

        # Override default
        messages = builder.render("greeting", {"name": "Bob", "location": "Mars"})
        assert messages[0].content == "Hello Bob from Mars!"

    def test_render_with_missing_allowed_variables(self):
        """Test rendering with allowed missing variables."""
        builder = BasePromptBuilder()

        builder.register_template("optional", "Hello {name}! {optional_msg}")
        builder.set_allowed_missing_variables(["optional_msg"])

        # Should not raise error for missing optional variable
        messages = builder.render("optional", {"name": "Charlie"})
        assert "Hello Charlie!" in messages[0].content

    def test_render_missing_required_variable(self):
        """Test error when required variable is missing."""
        builder = BasePromptBuilder()

        builder.register_template("required", "Hello {name}!")

        with pytest.raises(ValueError, match="Missing required variable: name"):
            builder.render("required", {})

    def test_get_template_variables(self):
        """Test variable extraction."""
        builder = BasePromptBuilder()

        builder.register_template("multi_var", "Hello {name} from {location} at {time}!")
        variables = builder.get_template_variables("multi_var")

        assert set(variables) == {"name", "location", "time"}

    def test_partial_binding(self):
        """Test partial variable binding."""
        builder = BasePromptBuilder()

        builder.register_template("partial_test", "Hello {name} from {location}!")

        # Create partial with location bound
        partial_builder = builder.partial(location="Mars")

        # Should only need name now
        messages = partial_builder.render("partial_test", {"name": "Dave"})
        assert messages[0].content == "Hello Dave from Mars!"

    def test_partial_with_callable(self):
        """Test partial binding with callable."""
        builder = BasePromptBuilder()

        builder.register_template("time_test", "Current time: {timestamp}")

        # Bind with callable
        partial_builder = builder.partial(timestamp=lambda: "2024-01-01")

        messages = partial_builder.render("time_test", {})
        assert messages[0].content == "Current time: 2024-01-01"

    def test_langchain_style_apis(self):
        """Test LangChain-style invoke and format methods."""
        builder = BasePromptBuilder()

        builder.register_template("test", "Hello {name}!")

        # Test invoke
        messages = builder.invoke("test", {"name": "Eve"})
        assert len(messages) == 1
        assert messages[0].content == "Hello Eve!"

        # Test format
        formatted = builder.format("test", {"name": "Eve"})
        assert formatted == "Hello Eve!"

    def test_add_examples(self):
        """Test adding few-shot examples."""
        builder = BasePromptBuilder()

        # Register a simple template for testing
        builder.register_template(
            "simple_classification",
            "Classify: {text}\nCategories: {categories}\n\n{examples}Category:",
        )

        examples = [
            {"input": "apple", "output": "fruit"},
            {"input": "carrot", "output": "vegetable"},
        ]

        builder.add_examples("simple_classification", examples)

        # Render should include examples
        messages = builder.render(
            "simple_classification", {"text": "banana", "categories": "fruit, vegetable"}
        )

        content = messages[0].content
        assert "apple" in content
        assert "fruit" in content
        assert "carrot" in content
        assert "vegetable" in content

    def test_custom_example_template(self):
        """Test custom example formatting."""
        builder = BasePromptBuilder()

        examples = [{"word": "hello", "translation": "hola"}]
        builder.add_examples("translate", examples, "English: {word} → Spanish: {translation}")

        # Register a simple template that uses examples
        builder.register_template("translate", "Translate: {text}\n\n{examples}Translation:")

        messages = builder.render("translate", {"text": "goodbye"})
        content = messages[0].content
        assert "English: hello → Spanish: hola" in content

    def test_multimodal_content(self):
        """Test multimodal content configuration."""
        builder = BasePromptBuilder()

        builder.register_template("image_analysis", "Analyze: {image}")
        builder.add_image_content("image_analysis", "image", "url")

        messages = builder.render("image_analysis", {"image": "https://example.com/image.jpg"})
        assert "https://example.com/image.jpg" in messages[0].content

        # Check metadata
        metadata = builder.get_template_metadata("image_analysis")
        assert "image:url" in metadata["content_types"]

    def test_template_composition(self):
        """Test template composition."""
        builder = BasePromptBuilder()

        builder.register_template("part1", "First part")
        builder.register_template("part2", "Second part")

        builder.compose_templates("combined", ["part1", "part2"])

        template = builder.get_template("combined")
        assert "First part" in template
        assert "Second part" in template

    def test_output_schema(self):
        """Test output schema configuration."""
        builder = BasePromptBuilder()

        schema = {"type": "object", "properties": {"result": {"type": "string"}}}
        builder.set_output_schema("test", schema)

        instructions = builder.get_output_instructions("test")
        assert "JSON" in instructions
        assert json.dumps(schema) in instructions
        assert "result" in instructions

    def test_template_metadata(self):
        """Test template metadata retrieval."""
        builder = BasePromptBuilder()

        builder.register_template("meta_test", "Hello {name}! {optional}")
        builder.set_allowed_missing_variables(["optional"])
        builder.add_examples("meta_test", [{"name": "test", "greeting": "hi"}])

        metadata = builder.get_template_metadata("meta_test")

        assert "name" in metadata["variables"]
        assert "optional" in metadata["optional_variables"]
        assert metadata["has_examples"] is True
        assert metadata["example_count"] == 1

    def test_template_validation(self):
        """Test template validation."""
        builder = BasePromptBuilder()

        # Valid template
        builder.register_template("valid", "Hello {name}!")
        result = builder.validate_template("valid")
        assert result["valid"] is True
        assert len(result["errors"]) == 0

        # Template with warnings
        assert len(result["warnings"]) > 0  # name has no default

        # Invalid template (unmatched braces): rejected at registration with the parser's details
        with pytest.raises(ValidationError, match="invalid.*Unmatched opening brace"):
            builder.register_template("invalid", "Hello {name!")

        # validate_template parses again and reports without raising
        builder._templates["valid:1.0"] = "Hello {name!"
        result = builder.validate_template("valid")
        assert result["valid"] is False
        assert "Unmatched opening brace" in result["errors"][0]

    def test_default_templates_work(self):
        """Conditions and loops are written in .skye prompts (D76); they render with real roles."""
        builder = BasePromptBuilder()
        assert len(builder._templates) > 0, "No templates loaded"

        builder.register_template(
            "memory_agent_test",
            """prompt "memory_agent_test" {
  variables = {
    input = string
    episodic_memory = list({ content = string }, [])
  }
  message "user" {
    text = "You are an AI with memory."
    when episodic_memory {
      text = "## Past conversations:"
      each memory in episodic_memory { text = "{{ memory.content }}" }
    }
    text = "User: {{ input }}"
  }
}""",
        )
        messages = builder.render(
            "memory_agent_test",
            {
                "input": "Hello, do you remember me?",
                "episodic_memory": [{"content": "User said hello yesterday"}],
            },
        )
        assert len(messages) == 1
        assert "remember me" in messages[0].content
        assert "hello yesterday" in messages[0].content

        builder.register_template(
            "code_agent_test",
            """prompt "code_agent_test" {
  variables = {
    input = string
    programming_language = string("")
    task_type = string("")
  }
  message "system" {
    text = "You are a code assistant."
    when programming_language { text = "Language: {{ programming_language }}" }
    when task_type { text = "Task: {{ task_type }}" }
  }
  message "user" { text = "{{ input }}" }
}""",
        )
        messages = builder.render(
            "code_agent_test",
            {
                "input": "Write a function to sort a list",
                "programming_language": "Python",
                "task_type": "generation_code",
            },
        )
        assert [m.role for m in messages] == ["system", "user"]
        assert "Python" in messages[0].content
        assert "generation_code" in messages[0].content

    def test_role_based_messages(self):
        """Test role-based message creation."""
        builder = BasePromptBuilder()

        # Register template with role markers
        builder.register_template("chat_roles", "[SYSTEM]\nYou are helpful.\n\n[USER]\nHello!")
        builder.set_message_roles("chat_roles", {"system": "system", "user": "user"})

        messages = builder.render("chat_roles", {})

        # Should create multiple messages based on roles
        assert len(messages) >= 1
        # Content should be parsed correctly
        content = messages[0].content
        assert "helpful" in content or "Hello" in content

    def test_file_template_loading(self):
        """Test loading templates from files."""
        builder = BasePromptBuilder()

        # Create a temporary template file
        import os
        import tempfile

        with tempfile.NamedTemporaryFile(mode="w", suffix=".txt", delete=False) as f:
            f.write("File template: {content}")
            temp_file = f.name

        try:
            # Load from file
            builder.register_template("file_test", temp_file, from_string=False)

            messages = builder.render("file_test", {"content": "loaded from file"})
            assert "loaded from file" in messages[0].content
        finally:
            os.unlink(temp_file)

    def test_nonexistent_template_error(self):
        """Test error when template doesn't exist."""
        builder = BasePromptBuilder()

        with pytest.raises(KeyError, match="Template not found"):
            builder.render("nonexistent", {})

    def test_example_selectors(self):
        """Test different example selection strategies."""
        builder = BasePromptBuilder()

        examples = [{"input": f"example{i}", "output": f"result{i}"} for i in range(10)]
        builder.add_examples("selector_test", examples)

        # Test fixed selector (default)
        builder.set_example_selector("selector_test", "fixed", max_examples=3)
        selected = builder._select_examples("selector_test", {})
        assert len(selected) == 3
        assert selected[0]["input"] == "example0"

        # Test random selector
        builder.set_example_selector("selector_test", "random", max_examples=3)
        selected = builder._select_examples("selector_test", {})
        assert len(selected) == 3

    def test_agent_templates(self):
        """An agent prompt with memories and tools, written in .skye."""
        builder = BasePromptBuilder()
        builder.register_template(
            "agent_memory_recall",
            """prompt "agent_memory_recall" {
  variables = {
    input = string
    episodic_memory = list({ content = string, timestamp = string("") }, [])
    tools = list({ name = string, description = string }, [])
  }
  message "system" {
    text = "You are an AI with memory capabilities."
    when episodic_memory {
      text = "## Past conversations:"
      each memory in episodic_memory {
        when memory.timestamp { text = "- {{ memory.content }} ({{ memory.timestamp }})" }
        when not memory.timestamp { text = "- {{ memory.content }}" }
      }
    }
    when tools {
      text = "You can use these tools:"
      each tool in tools { text = "- \\"{{ tool.name }}\\": {{ tool.description }}" }
    }
  }
  message "user" { text = "{{ input }}" }
}""",
        )
        messages = builder.render(
            "agent_memory_recall",
            {
                "input": "What did we discuss before?",
                "episodic_memory": [
                    {"content": "User asked about weather", "timestamp": "2 hours ago"},
                    {"content": "User mentioned vacation plans"},
                ],
                "tools": [
                    {"name": "calculator", "description": "Performs mathematical calculations"},
                    {"name": "search", "description": "Searches for information"},
                ],
            },
        )
        system = messages[0].content
        assert "Past conversations:" in system
        assert "- User asked about weather (2 hours ago)" in system
        assert "- User mentioned vacation plans" in system
        assert '- "calculator": Performs mathematical calculations' in system
        assert messages[1].content == "What did we discuss before?"

    def test_text_template_with_a_control_tag_points_to_skye(self):
        """A text template keeps interpolation only (D76)."""
        builder = BasePromptBuilder()
        with pytest.raises(ValidationError, match=r"line 2.*when.*each"):
            builder.register_template(
                "t", "Text: {{ text }}\n{% if domain %}{{ domain }}{% endif %}"
            )  # noqa: E501
        builder.register_template("t", "Labels: {{ labels | map('name') | join(', ') }}")
        content = builder.render("t", {"labels": [{"name": "PERSON"}, {"name": "ORG"}]})[0].content
        assert content == "Labels: PERSON, ORG"

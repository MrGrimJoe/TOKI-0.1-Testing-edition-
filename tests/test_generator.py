"""
test_generator.py -- generator.py's name-extraction logic
(extract_explicit_name()/infer_filename()), split apart in BETA 0.3.55 so
orchestrator.py can ask "what should I name it?" on a miss instead of
generator.py silently defaulting to "generated_file" -- see
orchestrator.py's TestGenerateFileAsksForMissingName for the actual
ask/resume integration this enables. No Ollama/network calls here at
all -- generate_and_save()'s streaming itself isn't covered by this file,
only the pure-function name logic that runs before any model call.
"""

from generator import extract_explicit_name, infer_filename


class TestExtractExplicitName:
    def test_called_clause_is_extracted(self):
        assert extract_explicit_name("create a function called calculator") == "calculator"

    def test_named_clause_is_extracted(self):
        assert extract_explicit_name("make a function named my_calc") == "my_calc"

    def test_trailing_that_clause_does_not_leak_into_the_name(self):
        assert extract_explicit_name(
            "create a function called calculator that adds two numbers"
        ) == "calculator"

    def test_no_name_clause_returns_none(self):
        assert extract_explicit_name("write a script that sorts a list") is None
        assert extract_explicit_name("generate some code for me") is None

    def test_extension_already_given_is_kept_verbatim(self):
        assert extract_explicit_name("write me a script called hello.py") == "hello.py"

    def test_empty_string_returns_none(self):
        assert extract_explicit_name("") is None

    def test_called_with_nothing_after_it_returns_none_not_empty_string(self):
        # "called" with no name following (edge case, e.g. a cut-off
        # utterance ending exactly on the word "called") must count as
        # NO name given, not a technically-non-None empty string that
        # would slip past orchestrator.py's `is None` check.
        assert extract_explicit_name("create a function called") is None


class TestInferFilename:
    """infer_filename() itself is unchanged behavior-wise by the BETA
    0.3.55 split -- these confirm that refactor didn't quietly change
    its output. The "ask instead of silently default" fix lives in
    orchestrator.py, one layer up, not here."""

    def test_explicit_name_is_used(self):
        assert infer_filename("create a python file called calculator") == "calculator.py"

    def test_no_name_falls_back_to_generic_default(self):
        assert infer_filename("write some code for this") == "generated_file.txt"

    def test_extension_inferred_from_mentioned_language(self):
        assert infer_filename("write a javascript script called app") == "app.js"

    def test_extension_not_duplicated_if_user_already_gave_one(self):
        assert infer_filename("make me a python script called hello.py") == "hello.py"

    def test_default_name_still_gets_a_language_extension(self):
        assert infer_filename("write me a python script") == "generated_file.py"

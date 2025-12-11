"""Generate test_scenarios configuration for Google Colab audio generation script.

Reads all scenario YAML files and creates the test_scenarios dictionary
format needed by the gTTS-based audio generation script.
"""
from pathlib import Path
from typing import Dict, List, Tuple
import yaml


# Language code mapping: scenario format → (gTTS lang, gTTS TLD)
LANGUAGE_MAPPING = {
    "en-US": ("en", "us"),
    "en-GB": ("en", "co.uk"),
    "en-IN": ("en", "co.in"),
    "es-ES": ("es", "es"),
    "es-MX": ("es", "com.mx"),
    "es-AR": ("es", "com.ar"),
}


def load_scenario(yaml_path: Path) -> dict:
    """Load a scenario YAML file."""
    with open(yaml_path, 'r', encoding='utf-8') as f:
        return yaml.safe_load(f)


def get_language_config(lang_code: str) -> Tuple[str, str]:
    """Convert scenario language code to gTTS format.

    Args:
        lang_code: Language code like "en-US" or "es-ES"

    Returns:
        Tuple of (language, tld) for gTTS
    """
    if lang_code in LANGUAGE_MAPPING:
        return LANGUAGE_MAPPING[lang_code]

    # Fallback: extract base language
    lang = lang_code.split('-')[0]
    return (lang, "us" if lang == "en" else "es")


def generate_test_scenarios(scenarios_dir: Path) -> Dict[str, List[Tuple[str, str, str]]]:
    """Generate test_scenarios configuration from all YAML scenario files.

    Args:
        scenarios_dir: Directory containing scenario YAML files

    Returns:
        Dictionary in format: {scenario_id: [(lang, tld, text), ...]}
    """
    test_scenarios = {}

    # Find all YAML scenario files
    yaml_files = sorted(scenarios_dir.glob("*.yaml"))

    for yaml_path in yaml_files:
        scenario = load_scenario(yaml_path)

        scenario_id = scenario['id']
        participants = scenario['participants']
        events = scenario['events']
        expectations = scenario['expectations']

        # Build mapping: event_id → expected_text + source_language
        event_text_map = {}
        for transcript_exp in expectations.get('transcripts', []):
            event_id = transcript_exp['event_id']
            source_lang = transcript_exp['source_language']
            expected_text = transcript_exp['expected_text']
            event_text_map[event_id] = (source_lang, expected_text)

        # Generate turns following the event sequence
        turns = []
        sequence = expectations.get('sequence', [])

        for event_id in sequence:
            if event_id not in event_text_map:
                print(f"⚠️  Warning: {scenario_id} - Event '{event_id}' has no transcript expectation")
                continue

            source_lang, expected_text = event_text_map[event_id]
            lang, tld = get_language_config(source_lang)

            turns.append((lang, tld, expected_text))

        if turns:
            test_scenarios[scenario_id] = turns
            print(f"✓ Generated {len(turns)} turns for scenario: {scenario_id}")
        else:
            print(f"⚠️  Warning: No turns generated for scenario: {scenario_id}")

    return test_scenarios


def format_python_code(test_scenarios: Dict[str, List[Tuple[str, str, str]]]) -> str:
    """Format test_scenarios as Python code for the Colab script.

    Args:
        test_scenarios: Dictionary of scenarios and their turns

    Returns:
        Formatted Python code string
    """
    lines = ["test_scenarios = {"]

    for scenario_id, turns in test_scenarios.items():
        lines.append(f'    "{scenario_id}": [')

        for i, (lang, tld, text) in enumerate(turns):
            # Escape quotes in text
            escaped_text = text.replace('"', '\\"')

            # Add comment with turn number
            comment = f"# Turn {i+1}: {lang.upper()}-{tld.upper()}"
            lines.append(f"        {comment}")
            lines.append(f'        ("{lang}", "{tld}", "{escaped_text}"),')
            lines.append("")

        lines.append("    ],")
        lines.append("")

    lines.append("}")

    return "\n".join(lines)


def main():
    """Generate and print test_scenarios configuration."""
    # Find scenarios directory
    script_dir = Path(__file__).parent
    scenarios_dir = script_dir.parent / "scenarios"

    if not scenarios_dir.exists():
        print(f"❌ Error: Scenarios directory not found: {scenarios_dir}")
        return

    print(f"📂 Reading scenarios from: {scenarios_dir}")
    print(f"📄 Found {len(list(scenarios_dir.glob('*.yaml')))} scenario files\n")

    # Generate configuration
    test_scenarios = generate_test_scenarios(scenarios_dir)

    print(f"\n✅ Generated configuration for {len(test_scenarios)} scenarios")
    print("\n" + "="*80)
    print("Copy the code below into your Google Colab script:")
    print("="*80 + "\n")

    # Print formatted Python code
    python_code = format_python_code(test_scenarios)
    print(python_code)

    # Also save to file
    output_file = script_dir / "test_scenarios_generated.py"
    with open(output_file, 'w', encoding='utf-8') as f:
        f.write("# Auto-generated test_scenarios configuration\n")
        f.write("# Generated from scenario YAML files\n\n")
        f.write(python_code)

    print("\n" + "="*80)
    print(f"💾 Configuration also saved to: {output_file}")
    print("="*80)


if __name__ == "__main__":
    main()

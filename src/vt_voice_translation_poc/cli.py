"""Command-line interface for the voice translation POC."""

from __future__ import annotations

import asyncio
import os
from pathlib import Path
from typing import List, Optional, Tuple

import typer
from rich.console import Console
from rich.traceback import install as install_rich_traceback
from rich.panel import Panel


from .audio import build_audio_input
from .config import SpeechProvider, SpeechServiceSettings
from .providers import create_translator
from .websocket_server import WebSocketServer

install_rich_traceback(suppress=[typer])

app = typer.Typer(
    help="Proof of concept for Azure Speech translation with Personal Voice.",
)
console = Console()

SUPPORTED_BATCH_SUFFIXES = (".wav", ".m4a")


def _resolve_max_testing_files() -> Optional[int]:
    """Read MAX_TESTING_FILES from the environment and coerce to a usable limit."""
    value = os.getenv("MAX_TESTING_FILES")
    if value is None or value.strip() == "":
        return None
    try:
        limit = int(value)
    except ValueError as exc:
        raise typer.BadParameter(
            f"Invalid value for MAX_TESTING_FILES: {value!r}. Provide a non-negative integer."
        ) from exc
    if limit < 0:
        raise typer.BadParameter("MAX_TESTING_FILES cannot be negative.")
    return limit if limit > 0 else None


def _discover_audio_files(root: Path) -> List[Path]:
    """Find supported audio files within a directory tree."""
    candidates = sorted(
        path
        for path in root.rglob("*")
        if path.is_file()
        and path.suffix.lower() in SUPPORTED_BATCH_SUFFIXES
        and "-translation" not in path.stem
    )

    selected: List[Path] = []
    seen_parents: set[Path] = set()

    for path in candidates:
        parent = path.parent
        if parent not in seen_parents:
            selected.append(path)
            seen_parents.add(parent)

    return selected


def _play_audio_preview(audio_path: Path) -> None:
    """Play a WAV file through the default audio output as a quick preview."""
    if audio_path.suffix.lower() != ".wav":
        console.print(f"[yellow]Skipping preview for non-WAV input: {audio_path}[/yellow]")
        return

    try:
        import sounddevice as sd
        import numpy as np
        import wave
    except Exception as exc:  # pragma: no cover - playback dependency missing
        console.print(f"[yellow]Audio preview unavailable ({exc}); continuing without playback.[/yellow]")
        return

    try:
        with wave.open(str(audio_path), "rb") as wav_file:
            sample_width = wav_file.getsampwidth()
            if sample_width == 2:
                dtype = np.int16
            elif sample_width == 1:
                dtype = np.uint8
            else:
                console.print(
                    f"[yellow]Unsupported sample width ({sample_width} bytes) for preview: {audio_path.name}[/yellow]"
                )
                return

            frames = wav_file.readframes(wav_file.getnframes())
            if not frames:
                console.print(f"[yellow]No audio frames to preview in {audio_path.name}[/yellow]")
                return

            audio_array = np.frombuffer(frames, dtype=dtype)
            channels = wav_file.getnchannels()
            if channels > 1:
                audio_array = audio_array.reshape(-1, channels)

            sd.play(audio_array, samplerate=wav_file.getframerate())
            sd.wait()
    except Exception as exc:  # pragma: no cover - playback failure
        console.print(f"[yellow]Failed to play preview for {audio_path.name}: {exc}[/yellow]")


def _translate_single(
    *,
    input_file: Optional[Path],
    settings: SpeechServiceSettings,
    from_language: str,
    to_language: List[str],
    voice: Optional[str],
    output_audio: Optional[Path],
) -> None:
    """Run translation for a single file or microphone input."""
    if voice and output_audio is None:
        default_name = f"{to_language[0]}-translation.wav"
        output_audio = Path("artifacts") / default_name
        console.print(
            f"[bold cyan]No --output-audio provided; defaulting to {output_audio}[/bold cyan]"
        )

    translator = create_translator(
        settings,
        from_language=from_language,
        to_languages=to_language,
        voice_name=voice,
        output_audio_path=output_audio,
    )

    # Use streaming microphone for Voice Live when no input file is provided
    use_streaming_microphone = (
        settings.provider is SpeechProvider.VOICE_LIVE and input_file is None
    )

    with build_audio_input(input_file, use_streaming_microphone=use_streaming_microphone) as audio_input:
        try:
            outcome = translator.translate(audio_input)
        except NotImplementedError as exc:
            console.print(f"[bold red]{exc}[/bold red]")
            raise typer.Exit(code=3) from exc

    if not outcome.success:
        raise typer.Exit(code=1)


def _translate_folder(
    *,
    folder: Path,
    settings: SpeechServiceSettings,
    from_language: str,
    to_language: List[str],
    voice: Optional[str],
) -> None:
    """Run translations for each supported file inside a folder."""
    files = _discover_audio_files(folder)
    if not files:
        raise typer.BadParameter(
            f"No .wav or .m4a files found under {folder}. Add files before running --input-folder."
        )

    raw_testing_limit = os.getenv("MAX_TESTING_FILES")
    limit = _resolve_max_testing_files()
    if limit is not None:
        files = files[:limit]
        console.print(
            f"[bold cyan]Limiting batch to first {limit} file(s) due to MAX_TESTING_FILES.[/bold cyan]"
        )

    total = len(files)
    console.print(f"[bold green]Discovered {total} eligible audio file(s) under {folder}.[/bold green]")

    failures: list[Tuple[Path, str | None]] = []
    preview_inputs = raw_testing_limit is not None

    for index, file_path in enumerate(files, start=1):
        try:
            relative_name = file_path.relative_to(folder)
        except ValueError:
            relative_name = file_path.name

        console.rule(f"[bold magenta]Session {index}/{total}[/bold magenta] • {relative_name}")
        console.print(
            Panel.fit(
                f"Starting batch translation for {file_path}",
                title="Batch file",
                style="bold cyan",
            )
        )

        per_file_output: Optional[Path] = None
        if voice:
            per_file_output = file_path.with_name(f"{file_path.stem}-translation.wav")

        translator = create_translator(
            settings,
            from_language=from_language,
            to_languages=to_language,
            voice_name=voice,
            output_audio_path=per_file_output,
            terminate_on_completion=True,
        )

        with build_audio_input(file_path, use_streaming_microphone=False) as audio_input:
            if preview_inputs and audio_input.source_path:
                console.print(
                    Panel.fit(
                        f"Playing input preview for {audio_input.source_path}",
                        title="Input preview",
                        style="bold blue",
                    )
                )
                _play_audio_preview(audio_input.source_path)

            try:
                outcome = translator.translate(audio_input)
            except NotImplementedError as exc:
                console.print(f"[bold red]{exc}[/bold red]")
                raise typer.Exit(code=3) from exc

        if outcome.success:
            console.print(
                Panel.fit(
                    "Translation completed successfully.",
                    title="Batch file",
                    style="bold green",
                )
            )
        else:
            message = outcome.error_details or "Translation failed."
            console.print(
                Panel.fit(
                    message,
                    title="Batch failure",
                    style="bold red",
                )
            )
            failures.append((file_path, outcome.error_details))

    if failures:
        summary_lines = [
            f"{path}: {details or 'No details provided'}" for path, details in failures
        ]
        console.print(
            Panel.fit(
                "\n".join(summary_lines),
                title=f"{len(failures)} translation(s) failed",
                style="bold red",
            )
        )
        raise typer.Exit(code=1)


@app.callback(invoke_without_command=True)
def main_callback(
    ctx: typer.Context,
    input_file: Optional[Path] = typer.Option(
        None,
        "--input-file",
        "-i",
        exists=True,
        file_okay=True,
        dir_okay=False,
        readable=True,
        help="Optional audio file input. Supports WAV and MP3.",
    ),
    input_folder: Optional[Path] = typer.Option(
        None,
        "--input-folder",
        exists=True,
        file_okay=False,
        dir_okay=True,
        readable=True,
        help="Directory containing audio files (.wav, .m4a) to translate sequentially.",
    ),
    from_language: str = typer.Option(
        "en-US",
        "--from-language",
        "-f",
        help="Locale of the source speech (e.g. en-US).",
    ),
    to_language: List[str] = typer.Option(
        ["es"],
        "--to-language",
        "-t",
        help="Target translation language(s) (e.g. es, fr). Provide multiple flags for multiple targets.",
    ),
    voice: Optional[str] = typer.Option(
        None,
        "--voice",
        "-v",
        help="Neural voice name for synthesized translation (requires exactly one --to-language).",
    ),
    output_audio: Optional[Path] = typer.Option(
        None,
        "--output-audio",
        "-o",
        dir_okay=False,
        writable=True,
        help="Path to save synthesized audio. Required when --voice is provided unless defaulting is acceptable.",
    ),
    dotenv_path: Optional[Path] = typer.Option(
        None,
        "--dotenv-path",
        help="Optional path to a .env file containing Azure Speech credentials.",
    ),
) -> None:
    """
    Translate speech from microphone or audio file using Azure's Live Interpreter preview or Voice Live.

    When no --input-file is provided, uses microphone input:
    - Live Interpreter: Uses Azure SDK's default microphone
    - Voice Live: Uses streaming microphone (pyaudio) for real-time capture
    
    When a neural voice is provided, synthesized audio is written to disk.
    """
    # If a subcommand was invoked, don't run the default translate logic
    if ctx.invoked_subcommand is not None:
        return

    if not to_language:
        raise typer.BadParameter("Please specify at least one --to-language.")

    if input_file and input_folder:
        raise typer.BadParameter("Please provide either --input-file or --input-folder, not both.")

    if input_folder and output_audio is not None:
        raise typer.BadParameter(
            "--output-audio cannot be combined with --input-folder; outputs are saved alongside each input file."
        )

    try:
        settings = SpeechServiceSettings.from_env(dotenv_path=str(dotenv_path) if dotenv_path else None)
    except RuntimeError as exc:  # pragma: no cover - runtime configuration loading
        raise typer.Exit(code=2) from exc

    if input_folder:
        _translate_folder(
            folder=input_folder,
            settings=settings,
            from_language=from_language,
            to_language=to_language,
            voice=voice,
        )
        return

    _translate_single(
        input_file=input_file,
        settings=settings,
        from_language=from_language,
        to_language=to_language,
        voice=voice,
        output_audio=output_audio,
    )


@app.command()
def translate(  # noqa: D401 - typer generates help text
    input_file: Optional[Path] = typer.Option(
        None,
        "--input-file",
        "-i",
        exists=True,
        file_okay=True,
        dir_okay=False,
        readable=True,
        help="Optional audio file input. Supports WAV and MP3.",
    ),
    input_folder: Optional[Path] = typer.Option(
        None,
        "--input-folder",
        exists=True,
        file_okay=False,
        dir_okay=True,
        readable=True,
        help="Directory containing audio files (.wav, .m4a) to translate sequentially.",
    ),
    from_language: str = typer.Option(
        "en-US",
        "--from-language",
        "-f",
        help="Locale of the source speech (e.g. en-US).",
    ),
    to_language: List[str] = typer.Option(
        ["es"],
        "--to-language",
        "-t",
        help="Target translation language(s) (e.g. es, fr). Provide multiple flags for multiple targets.",
    ),
    voice: Optional[str] = typer.Option(
        None,
        "--voice",
        "-v",
        help="Neural voice name for synthesized translation (requires exactly one --to-language).",
    ),
    output_audio: Optional[Path] = typer.Option(
        None,
        "--output-audio",
        "-o",
        dir_okay=False,
        writable=True,
        help="Path to save synthesized audio. Required when --voice is provided unless defaulting is acceptable.",
    ),
    dotenv_path: Optional[Path] = typer.Option(
        None,
        "--dotenv-path",
        help="Optional path to a .env file containing Azure Speech credentials.",
    ),
) -> None:
    """
    Translate speech from microphone or audio file using Azure's Live Interpreter preview or Voice Live.

    When no --input-file is provided, uses microphone input:
    - Live Interpreter: Uses Azure SDK's default microphone
    - Voice Live: Uses streaming microphone (pyaudio) for real-time capture
    
    When a neural voice is provided, synthesized audio is written to disk.
    """

    if not to_language:
        raise typer.BadParameter("Please specify at least one --to-language.")

    if input_file and input_folder:
        raise typer.BadParameter("Please provide either --input-file or --input-folder, not both.")

    if input_folder and output_audio is not None:
        raise typer.BadParameter(
            "--output-audio cannot be combined with --input-folder; outputs are saved alongside each input file."
        )

    try:
        print("Entering the app.command()")
        settings = SpeechServiceSettings.from_env(dotenv_path=str(dotenv_path) if dotenv_path else None)
        print("Entering the app.command()")
    except RuntimeError as exc:  # pragma: no cover - runtime configuration loading
        print(exc)
        raise typer.Exit(code=2) from exc

    if input_folder:
        _translate_folder(
            folder=input_folder,
            settings=settings,
            from_language=from_language,
            to_language=to_language,
            voice=voice,
        )
        return

    _translate_single(
        input_file=input_file,
        settings=settings,
        from_language=from_language,
        to_language=to_language,
        voice=voice,
        output_audio=output_audio,
    )


@app.command()
def serve(  # noqa: D401 - typer generates help text
    host: str = typer.Option(
        "localhost",
        "--host",
        "-h",
        help="Host address to bind the WebSocket server to.",
    ),
    port: int = typer.Option(
        8765,
        "--port",
        "-p",
        help="Port number to bind the WebSocket server to.",
    ),
    from_language: str = typer.Option(
        "en-US",
        "--from-language",
        "-f",
        help="Locale of the source speech (e.g. en-US).",
    ),
    to_language: List[str] = typer.Option(
        ["es"],
        "--to-language",
        "-t",
        help="Target translation language(s) (e.g. es, fr). Provide multiple flags for multiple targets.",
    ),
    voice: Optional[str] = typer.Option(
        None,
        "--voice",
        "-v",
        help="Neural voice name for synthesized translation (requires exactly one --to-language).",
    ),
    play_input: bool = typer.Option(
        False,
        "--play-input",
        help="Enable local playback of input audio received from the client.",
    ),
    play_azure: bool = typer.Option(
        False,
        "--play-azure",
        help="Enable local playback of Azure's translated audio response.",
    ),
    testing: bool = typer.Option(
        False,
        "--testing",
        help="Enable testing mode: sends recognized text transcript back via WebSocket.",
    ),
    dotenv_path: Optional[Path] = typer.Option(
        None,
        "--dotenv-path",
        help="Optional path to a .env file containing Azure Speech credentials.",
    ),
) -> None:
    """
    Start a WebSocket server to receive audio data from external applications.

    The server listens for incoming WebSocket connections and receives audio data
    that will be processed and sent to Azure for translation.

    By default, no audio is played locally. Use flags to enable:
    - --play-input: Play the audio received from the client locally
    - --play-azure: Play Azure's translated audio response locally
    """
    if not to_language:
        raise typer.BadParameter("Please specify at least one --to-language.")

    try:
        settings = SpeechServiceSettings.from_env(dotenv_path=str(dotenv_path) if dotenv_path else None)
    except RuntimeError as exc:  # pragma: no cover - runtime configuration loading
        print(exc)
        raise typer.Exit(code=2) from exc

    server = WebSocketServer(
        settings,
        host=host,
        port=port,
        from_language=from_language,
        to_languages=to_language,
        voice=voice,
        play_input_audio=play_input,
        play_azure_audio=play_azure,
        testing_mode=testing,
    )

    try:
        asyncio.run(server.start())
    except KeyboardInterrupt:
        console.print("\n[yellow]Server stopped by user[/yellow]")
        raise typer.Exit(code=0)


def main() -> None:  # pragma: no cover - entrypoint wrapper
    app()


if __name__ == "__main__":  # pragma: no cover
    main()



"""Command-line interface for generic DOSRAVI operations and Willem runs."""

from __future__ import annotations

import argparse
import json
import os
import secrets
import shlex
import sys
from contextlib import ExitStack
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from . import __version__
from .agent import Agent
from .client import Client, ExecResult, RemoteError, TransferStats
from .protocol import Status
from .session import (
    SessionRecord,
    crc32_file,
    parse_legacy_willem_log,
    parse_willem_log,
    parse_willem_write_log,
    sha256_file,
    timing_summary,
    validate_read_images,
)
from .transport import (
    LoggedTransport,
    LoopbackTransport,
    SerialTransport,
    SocketTransport,
    Transport,
    TransportError,
)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="dosravi")
    parser.add_argument(
        "--version", action="version", version=f"%(prog)s {__version__}"
    )
    connection = parser.add_argument_group("connection")
    connection.add_argument("--serial", metavar="DEVICE")
    connection.add_argument("--baud", type=int, default=38400)
    connection.add_argument("--tcp", metavar="HOST:PORT")
    connection.add_argument(
        "--reference-root", metavar="DIRECTORY", help=argparse.SUPPRESS
    )
    connection.add_argument("--timeout", type=float, default=1.0)
    connection.add_argument(
        "--exec-timeout",
        type=float,
        default=300.0,
        help="completion wait after an EXEC STARTED event",
    )
    connection.add_argument("--retries", type=int, default=5)
    parser.add_argument("--session-dir", type=Path)
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("ping")
    sub.add_parser("info")
    sub.add_parser("list")
    put = sub.add_parser("put")
    put.add_argument("local", type=Path)
    put.add_argument("remote")
    get = sub.add_parser("get")
    get.add_argument("remote")
    get.add_argument("local", type=Path)
    crc = sub.add_parser("crc")
    crc.add_argument("remote")
    remove = sub.add_parser("remove")
    remove.add_argument("remote")
    execute = sub.add_parser("exec")
    execute.add_argument("--execution-id", type=lambda value: int(value, 0))
    execute.add_argument("--stdin-remote")
    execute.add_argument("program")
    execute.add_argument("args", nargs=argparse.REMAINDER)
    sub.add_parser("quit")
    update = sub.add_parser("update")
    update.add_argument("agent", type=Path, help="new DOSRAVI.COM build")
    update.add_argument("--expect-version", required=True)
    link_test = sub.add_parser("link-test")
    link_test.add_argument("--size", type=int, default=65536)
    link_test.add_argument("--passes", type=int, default=3)
    link_test.add_argument("--note", action="append", default=[], metavar="KEY=VALUE")
    run = sub.add_parser("run")
    run.add_argument("--put", action="append", default=[], metavar="LOCAL:REMOTE")
    run.add_argument("--exec", dest="execution", required=True)
    run.add_argument("--execution-id", type=lambda value: int(value, 0))
    run.add_argument("--stdin", type=Path, help="file supplied to child DOS stdin")
    run.add_argument("--get", action="append", default=[], metavar="REMOTE[:LOCAL]")
    run.add_argument("--note", action="append", default=[], metavar="KEY=VALUE")
    willem = sub.add_parser("willem-read")
    willem.add_argument("--program", type=Path, required=True)
    willem.add_argument("--device", required=True)
    willem.add_argument("--lpt", default="378")
    willem.add_argument("--count", type=int, default=10)
    willem.add_argument("--output", type=Path, required=True)
    willem.add_argument("--trusted", type=Path)
    willem.add_argument("--profile")
    willem.add_argument(
        "--legacy-current",
        action="store_true",
        help="parse the unmodified Willem 0.0.5 append-log baseline",
    )
    willem.add_argument("--trace-on-failure", action="store_true")
    willem.add_argument("--note", action="append", default=[], metavar="KEY=VALUE")
    sweep = sub.add_parser("willem-sweep")
    sweep.add_argument("--program", type=Path, required=True)
    sweep.add_argument("--device", required=True)
    sweep.add_argument("--lpt", default="378")
    sweep.add_argument(
        "--profiles",
        required=True,
        help="comma-separated conservative-to-aggressive named profiles",
    )
    sweep.add_argument("--output", type=Path, required=True)
    sweep.add_argument("--trusted", type=Path)
    sweep.add_argument("--trace-on-failure", action="store_true")
    sweep.add_argument("--note", action="append", default=[], metavar="KEY=VALUE")
    write = sub.add_parser("willem-write")
    write.add_argument("--program", type=Path, required=True)
    write.add_argument("--device", choices=("28C64",), required=True)
    write.add_argument("--image", type=Path, required=True)
    write.add_argument("--gate", type=Path, required=True, help="reviewed WRITE.OK")
    write.add_argument("--lpt", default="378")
    write.add_argument("--read-profile", required=True)
    write.add_argument("--output", type=Path, required=True)
    write.add_argument(
        "--write", action="store_true", help="required explicit authorization"
    )
    write.add_argument("--trace-on-failure", action="store_true")
    write.add_argument("--note", action="append", default=[], metavar="KEY=VALUE")
    return parser


def _open_transport(
    args: argparse.Namespace, stack: ExitStack
) -> tuple[Transport, dict[str, Any]]:
    choices = sum(
        value is not None for value in (args.serial, args.tcp, args.reference_root)
    )
    if choices != 1:
        raise SystemExit("select exactly one of --serial or --tcp")
    if args.serial:
        transport: Transport = SerialTransport(args.serial, args.baud)
        description: dict[str, Any] = {
            "type": "serial",
            "device": args.serial,
            "baud": args.baud,
        }
    elif args.tcp:
        host, separator, port = args.tcp.rpartition(":")
        if not separator or not host:
            raise SystemExit("--tcp must be HOST:PORT")
        transport = SocketTransport(host, int(port))
        description = {"type": "tcp", "host": host, "port": int(port)}
    else:
        agent = Agent(args.reference_root)
        transport = LoopbackTransport(agent.receive)
        description = {
            "type": "reference",
            "root": str(Path(args.reference_root).resolve()),
        }
    description.update(
        {
            "timeout_seconds": args.timeout,
            "exec_timeout_seconds": args.exec_timeout,
            "retries": args.retries,
        }
    )
    stack.callback(transport.close)
    return transport, description


def _stats(stats: TransferStats) -> dict[str, Any]:
    return {
        "bytes": stats.bytes,
        "elapsed_seconds": stats.elapsed,
        "bytes_per_second": stats.bytes_per_second,
        "crc32": f"{stats.crc32:08x}",
    }


def _persistent_execution_ids(
    directory: Path, kind: str, identities: list[str]
) -> tuple[list[int], Path]:
    manifest = directory / "executions.json"
    if manifest.exists():
        try:
            saved = json.loads(manifest.read_text(encoding="utf-8"))
            execution_ids = saved["execution_ids"]
        except (OSError, ValueError, KeyError, TypeError) as exc:
            raise RuntimeError(f"invalid execution manifest: {manifest}") from exc
        if (
            saved.get("kind") != kind
            or saved.get("identities") != identities
            or not isinstance(execution_ids, list)
            or len(execution_ids) != len(identities)
            or any(
                not isinstance(value, int) or not 1 <= value <= 0xFFFFFFFF
                for value in execution_ids
            )
            or len(set(execution_ids)) != len(execution_ids)
        ):
            raise RuntimeError(
                "execution manifest does not match this operation; use a new output directory"
            )
        return execution_ids, manifest
    execution_ids: list[int] = []
    while len(execution_ids) < len(identities):
        candidate = secrets.randbits(32) or 1
        if candidate not in execution_ids:
            execution_ids.append(candidate)
    payload = {
        "kind": kind,
        "identities": identities,
        "execution_ids": execution_ids,
    }
    temporary = manifest.with_name(manifest.name + ".tmp")
    with temporary.open("w", encoding="utf-8") as stream:
        json.dump(payload, stream, indent=2, sort_keys=True)
        stream.write("\n")
        stream.flush()
        os.fsync(stream.fileno())
    temporary.replace(manifest)
    return execution_ids, manifest


def _split_mapping(value: str, require_local: bool = True) -> tuple[str, str]:
    if ":" in value:
        left, right = value.split(":", 1)
    elif require_local:
        raise SystemExit(f"expected LOCAL:REMOTE mapping: {value}")
    else:
        left, right = value, value
    if not left or not right:
        raise SystemExit(f"invalid mapping: {value}")
    return left, right


def _download_execution(
    client: Client,
    result: ExecResult,
    destination: Path,
    record: SessionRecord,
    artifact_prefix: str = "",
) -> None:
    destination.mkdir(parents=True, exist_ok=True)
    for remote, local_name in (
        (result.stdout_path, "STDOUT.TXT"),
        (result.stderr_path, "STDERR.TXT"),
    ):
        local = destination / local_name
        stats = client.get(remote, local)
        record.serial_stats[f"get:{remote}"] = _stats(stats)
        record.add_artifact(local, artifact_prefix + local_name)


def _generic(
    args: argparse.Namespace, client: Client, record: SessionRecord | None
) -> int:
    if args.command == "ping":
        print(client.ping())
    elif args.command == "info":
        print(json.dumps(client.info(), indent=2, sort_keys=True))
    elif args.command == "list":
        print(json.dumps(client.list(), indent=2, sort_keys=True))
    elif args.command == "put":
        print(json.dumps(_stats(client.put(args.local, args.remote)), indent=2))
    elif args.command == "get":
        print(json.dumps(_stats(client.get(args.remote, args.local)), indent=2))
    elif args.command == "crc":
        size, crc = client.crc(args.remote)
        print(json.dumps({"size": size, "crc32": f"{crc:08x}"}, indent=2))
    elif args.command == "remove":
        client.remove(args.remote)
    elif args.command == "exec":
        if args.execution_id is not None and not 1 <= args.execution_id <= 0xFFFFFFFF:
            raise SystemExit("--execution-id must be in 1..0xffffffff")
        result = client.execute(
            args.program,
            " ".join(args.args),
            args.execution_id,
            args.stdin_remote,
        )
        print(json.dumps(result.__dict__, indent=2))
    elif args.command == "quit":
        client.quit()
    elif args.command == "update":
        stats = client.put(args.agent, "DOSRAVI.NEW")
        client.stage_update("DOSRAVI.NEW", stats.bytes, stats.crc32)
        # The launcher swaps agents after the staging response. Bytes sent in
        # that gap may be lost, so use the normal bounded retry path.
        try:
            pong = client.ping()
            info = client.info()
        except TransportError as exc:
            raise RuntimeError(
                "replacement agent did not answer; reset the DOS machine to trigger fallback"
            ) from exc
        if (
            pong != "PONG"
            or info.get("agent") != "DOSRAVI.COM"
            or info.get("protocol") != 1
            or info.get("version") != args.expect_version
        ):
            try:
                client.rollback_update()
            finally:
                raise RuntimeError(
                    "replacement agent identity/version check failed; rollback requested"
                )
        client.confirm_update()
        print(
            json.dumps(
                {"updated": True, "agent": info, "fallback": "DOSRAVI.OLD"}, indent=2
            )
        )
    elif args.command == "link-test":
        assert record is not None
        if not 1 <= args.size <= 16 * 1024 * 1024 or not 1 <= args.passes <= 100:
            raise SystemExit("link-test requires 1..16777216 bytes and 1..100 passes")
        source = args.session_dir / "link-source.bin"
        source.write_bytes(
            bytes((index * 131 + (index >> 8)) & 0xFF for index in range(args.size))
        )
        record.add_artifact(source)
        for pass_number in range(1, args.passes + 1):
            put_stats = client.put(source, "LINK.BIN")
            destination = args.session_dir / f"link-return-{pass_number:03d}.bin"
            get_stats = client.get("LINK.BIN", destination)
            if destination.read_bytes() != source.read_bytes():
                raise RuntimeError(f"link-test pass {pass_number} byte mismatch")
            record.serial_stats[f"pass-{pass_number:03d}:put"] = _stats(put_stats)
            record.serial_stats[f"pass-{pass_number:03d}:get"] = _stats(get_stats)
            record.add_artifact(destination)
        client.remove("LINK.BIN")
        record.exit_status = 0
        print(json.dumps(record.serial_stats, indent=2, sort_keys=True))
    elif args.command == "run":
        assert record is not None
        for mapping in args.put:
            local, remote = _split_mapping(mapping)
            stats = client.put(local, remote)
            record.serial_stats[f"put:{remote}"] = _stats(stats)
            record.add_artifact(Path(local), f"upload:{remote}")
        words = shlex.split(args.execution)
        if not words:
            raise SystemExit("--exec cannot be empty")
        stdin_remote = None
        if args.stdin is not None:
            stdin_remote = "STDIN.TXT"
            stdin_stats = client.put(args.stdin, stdin_remote)
            record.serial_stats[f"put:{stdin_remote}"] = _stats(stdin_stats)
            record.add_artifact(args.stdin, f"upload:{stdin_remote}")
        execution_id = args.execution_id
        if execution_id is None:
            identities = [
                json.dumps(
                    {
                        "execution": args.execution,
                        "uploads": [
                            {
                                "mapping": mapping,
                                "sha256": sha256_file(Path(_split_mapping(mapping)[0])),
                            }
                            for mapping in args.put
                        ],
                        "stdin_sha256": (
                            sha256_file(args.stdin) if args.stdin is not None else None
                        ),
                    },
                    sort_keys=True,
                    separators=(",", ":"),
                )
            ]
            execution_ids, manifest = _persistent_execution_ids(
                args.session_dir, "generic-run-v1", identities
            )
            execution_id = execution_ids[0]
            record.add_artifact(manifest)
        if not 1 <= execution_id <= 0xFFFFFFFF:
            raise SystemExit("--execution-id must be in 1..0xffffffff")
        record.programmer_stats["execution_id"] = execution_id
        result = client.execute(
            words[0], " ".join(words[1:]), execution_id, stdin_remote
        )
        record.exit_status = result.exit_code
        record.programmer_stats["exec_elapsed_ms"] = result.elapsed_ms
        _download_execution(client, result, args.session_dir, record)
        for mapping in args.get:
            remote, local_name = _split_mapping(mapping, require_local=False)
            local = args.session_dir / local_name
            stats = client.get(remote, local)
            record.serial_stats[f"get:{remote}"] = _stats(stats)
            record.add_artifact(local)
        print(json.dumps(result.__dict__, indent=2))
        return result.exit_code
    else:
        raise AssertionError(args.command)
    return 0


def _capture_willem_trace(
    client: Client,
    command_args: str,
    trace_dir: Path,
    record: SessionRecord,
    artifact_prefix: str,
) -> None:
    traced = client.execute("WILLEM.COM", command_args + " /TRACE")
    _download_execution(client, traced, trace_dir, record, artifact_prefix)
    for remote in ("WILLEM.LOG", "WTRACE.BIN"):
        try:
            local = trace_dir / remote
            stats = client.get(remote, local)
            record.serial_stats[f"{artifact_prefix}get:{remote}"] = _stats(stats)
            record.add_artifact(local, artifact_prefix + remote)
        except (RemoteError, TransportError):
            record.transactions.append(
                {
                    "warning": "trace artifact unavailable",
                    "remote": remote,
                    "prefix": artifact_prefix,
                }
            )


def _validate_willem_tokens(device: str, lpt: str, profile: str | None) -> None:
    if (
        not device.isascii()
        or not 1 <= len(device) <= 16
        or any(not character.isalnum() for character in device)
    ):
        raise SystemExit("--device must be a 1..16 character ASCII identifier")
    if (
        not lpt.isascii()
        or not 1 <= len(lpt) <= 4
        or any(character not in "0123456789abcdefABCDEF" for character in lpt)
    ):
        raise SystemExit("--lpt must be a 1..4 digit hexadecimal I/O address")
    if profile is not None and (
        not profile.isascii()
        or not 1 <= len(profile) <= 24
        or any(not (character.isalnum() or character in "_-") for character in profile)
    ):
        raise SystemExit("timing profile must use 1..24 ASCII letters, digits, _ or -")


def _willem_read(
    args: argparse.Namespace, client: Client, record: SessionRecord
) -> int:
    if args.count != 10:
        raise SystemExit("the acceptance runner requires exactly --count 10")
    legacy_current = getattr(args, "legacy_current", False)
    if legacy_current and args.profile:
        raise SystemExit("--legacy-current and --profile are mutually exclusive")
    _validate_willem_tokens(args.device, args.lpt, args.profile)
    args.output.mkdir(parents=True, exist_ok=True)
    put_stats = client.put(args.program, "WILLEM.COM")
    record.serial_stats["put:WILLEM.COM"] = _stats(put_stats)
    record.add_artifact(args.program, "upload:WILLEM.COM")
    program_sha256 = sha256_file(args.program)
    if args.trusted is not None and not any(
        artifact.name == "trusted-reference" for artifact in record.artifacts
    ):
        record.add_artifact(args.trusted, "trusted-reference")
    trusted_sha256 = sha256_file(args.trusted) if args.trusted is not None else "none"
    command_arguments = []
    for index in range(1, 11):
        image_name = f"READ{index:02d}.BIN"
        command_args = f"R{args.device} {image_name} {args.lpt}"
        if args.profile:
            command_args += f" /PROFILE:{args.profile}"
        command_arguments.append(command_args)
    execution_ids, execution_manifest = _persistent_execution_ids(
        args.output,
        "willem-read-v1",
        [
            f"{program_sha256}:{trusted_sha256}:{legacy_current}:{command_args}"
            for command_args in command_arguments
        ],
    )
    record.add_artifact(execution_manifest, f"{args.output.name}/executions.json")
    images: list[Path] = []
    timings: list[int] = []
    profile_parameters: dict[str, Any] | None = None
    trials: list[dict[str, Any]] = []
    record.programmer_stats["acceptance_passed"] = False
    record.programmer_stats["trials"] = trials
    for index in range(1, 11):
        image_name = f"READ{index:02d}.BIN"
        command_args = command_arguments[index - 1]
        result = client.execute("WILLEM.COM", command_args, execution_ids[index - 1])
        record.exit_status = result.exit_code
        trials.append(
            {
                "trial": index,
                "exit_status": result.exit_code,
                "exec_elapsed_ms": result.elapsed_ms,
            }
        )
        trial = args.output / f"trial-{index:02d}"
        trial.mkdir(exist_ok=True)
        artifact_prefix = f"{args.output.name}/trial-{index:02d}/"
        _download_execution(client, result, trial, record, artifact_prefix)
        downloaded: dict[str, Path] = {}
        for remote in (image_name, "WILLEM.LOG"):
            local = trial / remote
            try:
                stats = client.get(remote, local)
            except (RemoteError, TransportError):
                if result.exit_code:
                    continue
                raise
            record.serial_stats[f"trial-{index:02d}:get:{remote}"] = _stats(stats)
            record.add_artifact(local, artifact_prefix + remote)
            downloaded[remote] = local
        if result.exit_code:
            record.exit_status = result.exit_code
            record.programmer_stats["acceptance_error"] = (
                f"trial {index} exited with status {result.exit_code}"
            )
            if args.trace_on_failure:
                _capture_willem_trace(
                    client,
                    command_args,
                    trial / "trace-diagnostic",
                    record,
                    artifact_prefix + "trace-diagnostic/",
                )
            raise RuntimeError(
                f"Willem read {index} failed with exit status {result.exit_code}"
            )
        try:
            if legacy_current:
                metrics = parse_legacy_willem_log(downloaded["WILLEM.LOG"], args.device)
            else:
                metrics = parse_willem_log(downloaded["WILLEM.LOG"], args.profile)
        except ValueError as exc:
            record.programmer_stats["acceptance_error"] = str(exc)
            raise
        trials[-1]["programmer"] = metrics
        if args.profile:
            trial_parameters = metrics["parameters"]
            if profile_parameters is None:
                profile_parameters = trial_parameters
                record.programmer_stats["profile_parameters"] = profile_parameters
            elif trial_parameters != profile_parameters:
                error = "profile parameters changed between acceptance trials"
                record.programmer_stats["acceptance_error"] = error
                raise ValueError(error)
        images.append(trial / image_name)
        timings.append(metrics["read_ms"])
        record.programmer_stats["local_read_timing"] = timing_summary(timings)
        try:
            record.programmer_stats["read_acceptance"] = validate_read_images(
                images, args.trusted
            )
        except ValueError as exc:
            record.programmer_stats["acceptance_error"] = str(exc)
            if args.trace_on_failure:
                _capture_willem_trace(
                    client,
                    command_args,
                    args.output / "mismatch-trace",
                    record,
                    f"{args.output.name}/mismatch-trace/",
                )
            raise
    record.programmer_stats["local_read_timing"] = timing_summary(timings)
    record.programmer_stats["acceptance_passed"] = True
    record.exit_status = 0
    return 0


def _willem_sweep(
    args: argparse.Namespace, client: Client, record: SessionRecord
) -> int:
    profiles = [profile.strip() for profile in args.profiles.split(",")]
    if len(profiles) < 2 or any(
        not profile
        or any(not (character.isalnum() or character in "_-") for character in profile)
        for profile in profiles
    ):
        raise SystemExit(
            "--profiles requires at least two comma-separated names using letters, digits, _ or -"
        )
    results: list[dict[str, Any]] = []
    record.programmer_stats["timing_sweep_runs"] = results

    def run_profile(profile: str, directory: str, phase: str) -> None:
        profile_args = argparse.Namespace(**vars(args))
        profile_args.count = 10
        profile_args.profile = profile
        profile_args.output = args.output / directory
        try:
            _willem_read(profile_args, client, record)
        except (RuntimeError, ValueError, RemoteError, TransportError) as exc:
            results.append(
                {
                    "profile": profile,
                    "phase": phase,
                    "passed": False,
                    "error": str(exc),
                }
            )
            raise
        results.append(
            {
                "profile": profile,
                "phase": phase,
                "passed": True,
                "acceptance": record.programmer_stats["read_acceptance"],
                "timing": record.programmer_stats["local_read_timing"],
                "parameters": record.programmer_stats.get("profile_parameters"),
            }
        )

    fastest_index = -1
    failure: RuntimeError | ValueError | RemoteError | TransportError | None = None
    for index, profile in enumerate(profiles):
        try:
            run_profile(profile, f"sweep-{index + 1:02d}-{profile}", "sweep")
            fastest_index = index
        except (RuntimeError, ValueError, RemoteError, TransportError) as exc:
            failure = exc
            break
    if fastest_index < 0:
        record.programmer_stats["timing_sweep"] = results
        raise RuntimeError(
            "the conservative profile failed; no sweep baseline exists"
        ) from failure

    # Detect drift after every aggressive attempt, including a mismatch.
    run_profile(profiles[0], "conservative-repeat", "drift-check")

    if fastest_index < 1:
        record.programmer_stats["timing_sweep"] = results
        raise RuntimeError(
            "no guarded production profile exists below the fastest passing profile"
        ) from failure
    production = profiles[fastest_index - 1]
    run_profile(production, f"production-{production}", "production-baseline")
    record.programmer_stats["timing_sweep"] = {
        "profiles": profiles,
        "fastest_passing": profiles[fastest_index],
        "production_baseline": production,
        "runs": results,
        "stopped_at_first_failure": failure is not None,
    }
    record.exit_status = 0
    return 0


def _willem_write(
    args: argparse.Namespace, client: Client, record: SessionRecord
) -> int:
    if not args.write:
        raise SystemExit("willem-write requires the explicit --write authorization")
    _validate_willem_tokens(args.device, args.lpt, args.read_profile)
    if args.image.stat().st_size != 8192:
        raise SystemExit("28C64 programming image must be exactly 8192 bytes")
    if not 1 <= args.gate.stat().st_size <= 512:
        raise SystemExit("reviewed WRITE.OK gate must contain 1..512 bytes")
    args.output.mkdir(parents=True, exist_ok=True)
    record.programmer_stats["write_passed"] = False
    program_sha256 = sha256_file(args.program)
    image_crc32 = f"{crc32_file(args.image):08x}"
    command_args = f"W{args.device} TARGET.BIN {args.lpt} /WRITE"
    write_identity = json.dumps(
        {
            "program_sha256": program_sha256,
            "image_crc32": image_crc32,
            "gate_sha256": sha256_file(args.gate),
            "command_args": command_args,
        },
        sort_keys=True,
        separators=(",", ":"),
    )
    execution_ids, execution_manifest = _persistent_execution_ids(
        args.output, "willem-write-v1", [write_identity]
    )
    record.add_artifact(execution_manifest, f"{args.output.name}/executions.json")
    inputs = (
        (args.program, "WILLEM.COM"),
        (args.image, "TARGET.BIN"),
        (args.gate, "WRITE.OK"),
    )
    for local, remote in inputs:
        record.add_artifact(local, f"upload:{remote}")
    write_dir = args.output / "programming"
    write_dir.mkdir(parents=True, exist_ok=True)
    log = write_dir / "WILLEM.LOG"
    if log.exists():
        try:
            write_metrics = parse_willem_write_log(log, image_crc32)
        except ValueError as exc:
            raise RuntimeError(
                "existing programming evidence is invalid; preserve it and use a new output directory"
            ) from exc
        record.programmer_stats["write_resumed_from_local_evidence"] = True
        record.exit_status = 0
    else:
        for local, remote in inputs:
            stats = client.put(local, remote)
            record.serial_stats[f"put:{remote}"] = _stats(stats)
        result = client.execute("WILLEM.COM", command_args, execution_ids[0])
        # WILLEM must consume its gate; removal here narrows accidental reuse
        # if the child left it behind after returning.
        try:
            client.remove("WRITE.OK")
        except RemoteError as exc:
            if exc.status != Status.NOT_FOUND:
                raise
        _download_execution(
            client, result, write_dir, record, f"{args.output.name}/programming/"
        )
        log_stats = client.get("WILLEM.LOG", log)
        record.serial_stats["programming:get:WILLEM.LOG"] = _stats(log_stats)
        record.exit_status = result.exit_code
        if result.exit_code:
            raise RuntimeError(
                f"Willem programming failed with status {result.exit_code}"
            )
        write_metrics = parse_willem_write_log(log, image_crc32)
    record.add_artifact(log, f"{args.output.name}/programming/WILLEM.LOG")
    if int(write_metrics["changed"]) + int(write_metrics["unchanged"]) != 8192:
        raise ValueError("write metric byte counts do not cover the complete 28C64")
    if int(write_metrics["retry_bytes"]) > int(write_metrics["changed"]) or int(
        write_metrics["late"]
    ) > int(write_metrics["changed"]):
        raise ValueError("write metric retry/late counts exceed changed bytes")
    record.programmer_stats["write"] = write_metrics

    # Independent full verification is part of the write metric, then the
    # normal accepted read path performs ten fresh power cycles and compares
    # every byte against the requested image.
    read_args = argparse.Namespace(
        program=args.program,
        device=args.device,
        lpt=args.lpt,
        count=10,
        output=args.output / "post-write-reads",
        trusted=args.image,
        profile=args.read_profile,
        trace_on_failure=args.trace_on_failure,
        legacy_current=False,
    )
    _willem_read(read_args, client, record)
    record.programmer_stats["write_passed"] = True
    record.exit_status = 0
    return 0


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    notes: dict[str, str] = {}
    for note in getattr(args, "note", []):
        key, separator, value = note.partition("=")
        if not separator or not key or not value:
            raise SystemExit(f"--note must be nonempty KEY=VALUE: {note}")
        if key in notes:
            raise SystemExit(f"duplicate hardware note: {key}")
        notes[key] = value
    if args.command in ("willem-read", "willem-sweep", "willem-write"):
        required_notes = {
            "datasheet",
            "machine",
            "programmer-revision",
            "chip-marking",
            "supply",
            "socket",
            "dip-switches",
            "cable-adapter",
        }
        if args.command == "willem-write":
            required_notes.update({"endurance", "erase-requirements"})
        missing_notes = sorted(required_notes - notes.keys())
        if missing_notes:
            raise SystemExit(
                f"{args.command} requires hardware notes: " + ", ".join(missing_notes)
            )
    if args.serial and args.command in ("run", "link-test"):
        missing_link_notes = sorted({"machine", "cable-adapter"} - notes.keys())
        if missing_link_notes:
            raise SystemExit(
                f"physical {args.command} requires hardware notes: "
                + ", ".join(missing_link_notes)
            )
    needs_session = args.command in (
        "run",
        "link-test",
        "willem-read",
        "willem-sweep",
        "willem-write",
    )
    if (
        needs_session
        and args.command in ("run", "link-test")
        and args.session_dir is None
    ):
        timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        args.session_dir = Path("sessions") / f"{args.command}-{timestamp}"
    if args.command in ("willem-read", "willem-sweep", "willem-write"):
        args.session_dir = args.output
    if needs_session:
        args.session_dir.mkdir(parents=True, exist_ok=True)
    with ExitStack() as stack:
        transport, description = _open_transport(args, stack)
        record = (
            SessionRecord.create(args.session_dir.name, __version__, description)
            if needs_session
            else None
        )
        if record is not None:
            record.command_line = sys.argv if argv is None else ["dosravi", *argv]
            rx = stack.enter_context((args.session_dir / "serial.rx").open("wb"))
            tx = stack.enter_context((args.session_dir / "serial.tx").open("wb"))
            transport = LoggedTransport(transport, rx, tx)
            events = stack.enter_context(
                (args.session_dir / "transactions.jsonl").open("w", encoding="utf-8")
            )

            def log_event(event: dict[str, object]) -> None:
                assert record is not None
                record.transactions.append(event)
                events.write(json.dumps(event, sort_keys=True) + "\n")
                events.flush()
        else:
            log_event = None
        client = Client(
            transport,
            args.timeout,
            args.retries,
            log_event,
            exec_timeout=args.exec_timeout,
        )
        try:
            if record is not None:
                record.negotiated = client.info()
                record.hardware_notes.update(notes)
            if args.command == "willem-read":
                assert record is not None
                status = _willem_read(args, client, record)
            elif args.command == "willem-sweep":
                assert record is not None
                status = _willem_sweep(args, client, record)
            elif args.command == "willem-write":
                assert record is not None
                status = _willem_write(args, client, record)
            else:
                status = _generic(args, client, record)
        except BaseException as exc:
            if record is not None:
                record.error = f"{type(exc).__name__}: {exc}"
            raise
        finally:
            if record is not None:
                record.finish()
                record.write(args.session_dir / "session.json")
        return status


if __name__ == "__main__":
    raise SystemExit(main())

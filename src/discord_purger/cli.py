from __future__ import annotations

import argparse
import asyncio
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

from rich.console import Console
from rich.progress import (
    BarColumn,
    MofNCompleteColumn,
    Progress,
    SpinnerColumn,
    TextColumn,
    TimeElapsedColumn,
    TimeRemainingColumn,
)

from discord_purger.client import AuthenticationError, DiscordClient
from discord_purger.engine import DeletionManifest, DeletionState, run_deletion
from discord_purger.parser import parse_data_package
from discord_purger.sweep import search_sweep

DISCORD_EPOCH_MS = 1420070400000


def snowflake_to_datetime(snowflake: str) -> datetime:
    ms = (int(snowflake) >> 22) + DISCORD_EPOCH_MS
    return datetime.fromtimestamp(ms / 1000, tz=timezone.utc)


def default_state_path() -> Path:
    if sys.platform == "win32":
        base = Path(os.environ.get("APPDATA", Path.home()))
    else:
        base = Path.home() / ".config"
    return base / "discord-purger" / "state.json"


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="discord-purger",
        description="Delete all your Discord messages and reactions.",
    )

    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument(
        "--package", type=Path,
        help="Path to Discord data package (zip or directory)",
    )
    source.add_argument(
        "--search-only", action="store_true",
        help="Run search sweep without a data package",
    )
    source.add_argument(
        "--status", nargs="?", const=True, metavar="PACKAGE",
        help="Show deletion progress from the state file. Optionally pass a package path for channel names.",
    )

    parser.add_argument(
        "--token",
        help="Discord user token (or set DISCORD_TOKEN env var)",
    )
    parser.add_argument(
        "--dry-run", action="store_true",
        help="Show what would be deleted without making API calls",
    )
    parser.add_argument(
        "--state", type=Path,
        help=f"Resume state file path (default: {default_state_path()})",
    )
    parser.add_argument(
        "--concurrency", type=int, default=10,
        help="Max parallel channel workers (default: 10)",
    )
    parser.add_argument(
        "--no-sweep", action="store_true",
        help="Skip the search sweep (only delete from data package)",
    )
    parser.add_argument(
        "--no-reactions", action="store_true",
        help="Skip reaction deletion",
    )
    parser.add_argument(
        "--full-purge", action="store_true",
        help="Also clear profile, reset nicknames, leave guilds, and unfriend everyone",
    )
    parser.add_argument(
        "--nuke", action="store_true",
        help="Delete everything: messages, reactions, sweep for stragglers, "
             "clear profile, leave guilds, unfriend everyone",
    )
    parser.add_argument(
        "-y", "--yes", action="store_true",
        help="Skip confirmation prompts",
    )
    parser.add_argument(
        "-v", "--verbose", action="count", default=0,
        help="Verbose output (-v per-guild/channel, -vv per-message details + rate limits)",
    )

    return parser.parse_args(argv)


def _confirm(console: Console, message: str, auto_yes: bool) -> bool:
    """Prompt for confirmation. Returns True if confirmed."""
    if auto_yes:
        return True
    console.print(f"\n{message}")
    try:
        response = console.input("[bold]Continue? [y/N] [/]").strip().lower()
    except (EOFError, KeyboardInterrupt):
        console.print("\nAborted.")
        return False
    return response in ("y", "yes")


async def async_main(args: argparse.Namespace, token: str) -> int:
    console = Console()
    verbose = args.verbose  # 0=quiet, 1=-v, 2+=-vv

    # --nuke implies full-purge and enables sweep
    if args.nuke:
        args.full_purge = True
        args.no_sweep = False

    manifest_messages: dict[str, list[str]] = {}
    manifest_reactions: list[tuple[str, str, str]] = []
    known_ids: set[str] = set()
    channel_names: dict[str, str] = {}  # channel_id -> "channel_name (guild_name)"
    user_id: str | None = None
    export_timestamp: datetime | None = None

    # Phase 1: Parse data package
    if args.package:
        console.print("\n[bold]Phase 1:[/] Parsing data package...")
        try:
            pkg = parse_data_package(args.package, skip_reactions=args.no_reactions)
        except (ValueError, OSError) as e:
            console.print(f"[red]Error parsing data package: {e}[/]")
            return 1

        user_id = pkg.user_id
        manifest_messages = pkg.messages_by_channel()
        if not args.no_reactions:
            manifest_reactions = pkg.reaction_tuples()
        known_ids = {mid for ids in manifest_messages.values() for mid in ids}
        for ch in pkg.channels:
            label = ch.channel_name
            if ch.guild_name:
                label = f"{ch.channel_name} ({ch.guild_name})"
            channel_names[ch.channel_id] = label

        # Derive export timestamp from newest message snowflake
        all_ids = [mid for ids in manifest_messages.values() for mid in ids]
        if all_ids:
            newest = max(all_ids, key=lambda x: int(x))
            export_timestamp = snowflake_to_datetime(newest)

        console.print(
            f"  Found {pkg.total_messages:,} messages "
            f"across {pkg.total_channels:,} channels"
        )
        if manifest_reactions:
            console.print(f"  Found {len(manifest_reactions):,} reactions")
        if pkg.warnings:
            console.print(f"  [yellow]{len(pkg.warnings)} warnings[/]")

    # Phase 2: Connect and optionally sweep
    do_sweep = not args.no_sweep
    need_client = do_sweep or not args.dry_run or getattr(args, "full_purge", False)

    if args.search_only or need_client:
        console.print("\n[bold]Connecting to Discord...[/]")

        try:
            async with DiscordClient(token) as client:
                me = await client.get_current_user()
                console.print(
                    f"  Authenticated as [bold]{me.get('username', '?')}[/] "
                    f"({me['id']})"
                )

                # Validate user ID matches data package
                if user_id is not None and me["id"] != user_id:
                    console.print(
                        f"[red]Token user ({me['id']}) does not match "
                        f"data package user ({user_id}). Aborting.[/]"
                    )
                    return 1

                if user_id is None:
                    user_id = me["id"]

                # Search sweep
                if do_sweep:
                    console.print("\n[bold]Phase 2:[/] Searching for messages...")

                    sweep_progress = Progress(
                        SpinnerColumn(),
                        TextColumn("[progress.description]{task.description}"),
                        BarColumn(),
                        MofNCompleteColumn(),
                        TimeElapsedColumn(),
                        console=console,
                    )

                    running_total = 0

                    with sweep_progress:
                        guild_task = sweep_progress.add_task(
                            "Discovering guilds...", total=None,
                        )
                        dm_task = None

                        def on_sweep_progress(event: str, name: str, count: int) -> None:
                            nonlocal running_total, dm_task

                            if event == "guilds_total":
                                sweep_progress.update(
                                    guild_task,
                                    total=count,
                                    description=f"Searching {count} guilds...",
                                )
                            elif event == "guild_start":
                                sweep_progress.update(
                                    guild_task,
                                    description=f"[{count}/{sweep_progress.tasks[guild_task].total:.0f}] {name}",
                                )
                            elif event == "guild_done":
                                running_total += count
                                sweep_progress.advance(guild_task)
                                if verbose:
                                    if count > 0:
                                        sweep_progress.console.print(
                                            f"    {name}: [green]{count}[/] messages"
                                        )
                                    else:
                                        sweep_progress.console.print(
                                            f"    [dim]{name}: 0 messages[/]"
                                        )
                            elif event == "guild_skipped":
                                sweep_progress.advance(guild_task)
                                if verbose:
                                    sweep_progress.console.print(
                                        f"    [yellow]{name}: skipped (inaccessible)[/]"
                                    )
                            elif event == "dms_total":
                                if count > 0:
                                    dm_task = sweep_progress.add_task(
                                        f"Searching {count} DM channels...",
                                        total=count,
                                    )
                            elif event == "dm_start":
                                if dm_task is not None:
                                    sweep_progress.update(
                                        dm_task,
                                        description=f"DM channels [{count}/{sweep_progress.tasks[dm_task].total:.0f}]",
                                    )
                            elif event == "dm_done":
                                running_total += count
                                if dm_task is not None:
                                    sweep_progress.advance(dm_task)
                                if verbose and count > 0:
                                    sweep_progress.console.print(
                                        f"    DM {name}: [green]{count}[/] messages"
                                    )

                        sweep_result = await search_sweep(
                            client,
                            user_id,
                            known_message_ids=known_ids or None,
                            export_timestamp=export_timestamp,
                            on_progress=on_sweep_progress,
                        )

                    console.print(
                        f"  Searched {sweep_result.guilds_searched} guilds, "
                        f"{sweep_result.dm_channels_searched} DM channels"
                    )
                    if sweep_result.guilds_skipped:
                        console.print(
                            f"  [yellow]{sweep_result.guilds_skipped} guilds skipped "
                            f"(inaccessible)[/]"
                        )
                    console.print(
                        f"  Found {sweep_result.messages_new:,} new messages"
                    )

                    # Merge into manifest
                    for ch, ids in sweep_result.messages_by_channel.items():
                        manifest_messages.setdefault(ch, []).extend(ids)

                # Phase 3: Delete
                manifest = DeletionManifest(
                    messages_by_channel=manifest_messages,
                    reactions=manifest_reactions,
                )

                if manifest.total_messages == 0 and manifest.total_reactions == 0:
                    if not args.full_purge:
                        console.print("\n[bold green]Nothing to delete.[/]")
                        return 0
                else:
                    # Confirm before deletion
                    if not args.dry_run:
                        scope_parts = []
                        scope_parts.append(f"[bold]{manifest.total_messages:,}[/] messages")
                        if manifest.total_reactions > 0:
                            scope_parts.append(f"[bold]{manifest.total_reactions:,}[/] reactions")
                        scope = " and ".join(scope_parts)
                        channels = len(manifest.messages_by_channel)
                        warn = f"[red]About to permanently delete {scope} across {channels:,} channels.[/]"
                        if not _confirm(console, warn, args.yes):
                            console.print("Aborted.")
                            return 0

                phase = "3" if do_sweep else "2"
                console.print(
                    f"\n[bold]Phase {phase}:[/] Deleting "
                    f"{manifest.total_messages:,} messages"
                    f" and {manifest.total_reactions:,} reactions..."
                )

                if args.dry_run:
                    console.print("[yellow]DRY RUN — no changes will be made[/]")

                state_path = args.state or default_state_path()
                if args.dry_run:
                    state_path = state_path.with_suffix(".dryrun.json")

                delete_progress = Progress(
                    SpinnerColumn(),
                    TextColumn("[progress.description]{task.description}"),
                    BarColumn(),
                    MofNCompleteColumn(),
                    TimeRemainingColumn(),
                    console=console,
                )

                with delete_progress:
                    msg_task = delete_progress.add_task(
                        "Messages", total=manifest.total_messages,
                    )
                    rxn_task = None
                    if manifest.total_reactions > 0:
                        rxn_task = delete_progress.add_task(
                            "Reactions", total=manifest.total_reactions,
                        )

                    channel_skip_counts: dict[str, int] = {}
                    channel_fail_counts: dict[str, int] = {}

                    def _ch_label(cid: str) -> str:
                        name = channel_names.get(cid)
                        return f"{name}" if name else f"Channel {cid}"

                    def on_delete_progress(event: str, channel_id: str, detail: str) -> None:
                        label = _ch_label(channel_id)
                        if event == "channel_start" and verbose >= 1:
                            delete_progress.console.print(
                                f"    [dim]{label}:[/] {detail} messages"
                            )
                        elif event == "channel_done" and verbose >= 1:
                            skips = channel_skip_counts.pop(channel_id, 0)
                            fails = channel_fail_counts.pop(channel_id, 0)
                            extra = ""
                            if skips or fails:
                                parts = []
                                if skips:
                                    parts.append(f"{skips} skipped")
                                if fails:
                                    parts.append(f"{fails} failed")
                                extra = f" ({', '.join(parts)})"
                            delete_progress.console.print(
                                f"    [green]{label}: done[/]{extra}"
                            )
                        elif event == "deleted":
                            delete_progress.advance(msg_task)
                        elif event == "skipped":
                            delete_progress.advance(msg_task)
                            channel_skip_counts[channel_id] = channel_skip_counts.get(channel_id, 0) + 1
                            if verbose >= 2:
                                delete_progress.console.print(
                                    f"      [yellow]skip {channel_id}/{detail}[/]"
                                )
                        elif event == "failed":
                            delete_progress.advance(msg_task)
                            channel_fail_counts[channel_id] = channel_fail_counts.get(channel_id, 0) + 1
                            if verbose >= 2:
                                delete_progress.console.print(
                                    f"      [red]fail {channel_id}/{detail}[/]"
                                )
                        elif event in ("reaction_deleted", "reaction_skipped") and rxn_task is not None:
                            delete_progress.advance(rxn_task)

                    result = await run_deletion(
                        client,
                        manifest,
                        dry_run=args.dry_run,
                        state_path=state_path,
                        max_concurrency=args.concurrency,
                        on_progress=on_delete_progress,
                    )

                # Summary
                console.print(f"\n[bold green]Done in {result.elapsed:.1f}s[/]")
                console.print(
                    f"  Messages: [green]{result.messages_deleted:,} deleted[/], "
                    f"[yellow]{result.messages_skipped:,} skipped[/], "
                    f"[red]{result.messages_failed:,} failed[/]"
                )
                if manifest.total_reactions > 0:
                    console.print(
                        f"  Reactions: [green]{result.reactions_deleted:,} deleted[/], "
                        f"[yellow]{result.reactions_skipped:,} skipped[/]"
                    )
                if verbose >= 2:
                    http = client._http
                    rl = http._rate_limiter
                    console.print(
                        f"  [dim]Rate limit stats: "
                        f"{rl.preemptive_waits} proactive waits, "
                        f"{http.rate_limit_hits} 429s hit, "
                        f"{rl.global_pauses} global pauses, "
                        f"{http.server_errors} server errors, "
                        f"{http.network_errors} network errors[/]"
                    )

                # Verification sweep (--nuke): search everything fresh, delete stragglers
                if args.nuke and not args.dry_run:
                    console.print("\n[bold]Verification sweep:[/] Searching for remaining messages...")
                    verify_result = await search_sweep(
                        client, user_id,
                        on_progress=on_sweep_progress if do_sweep else None,
                    )
                    stragglers = verify_result.messages_new
                    if stragglers > 0:
                        console.print(f"  Found {stragglers:,} remaining messages, deleting...")
                        verify_manifest = DeletionManifest(
                            messages_by_channel=verify_result.messages_by_channel,
                        )
                        await run_deletion(
                            client, verify_manifest,
                            state_path=state_path,
                            max_concurrency=args.concurrency,
                        )
                        console.print(f"  [green]Verification sweep complete[/]")
                    else:
                        console.print("  [green]Clean — no remaining messages found[/]")

                # Full purge: profile, nicknames, guilds, friends
                if args.full_purge:
                    await _run_full_purge(client, console, verbose, args.dry_run, args.yes)

        except AuthenticationError:
            console.print("[red]Authentication failed. Check your Discord token.[/]")
            return 1

    return 0


async def _run_full_purge(
    client: DiscordClient,
    console: Console,
    verbose: bool,
    dry_run: bool,
    auto_yes: bool = False,
) -> None:
    """Clear profile, reset nicknames, leave guilds, unfriend everyone."""
    # Preview what will happen and confirm
    guilds = await client.get_guilds()
    relationships = await client.get_relationships()

    if not dry_run:
        parts = ["clear your profile (avatar, bio, banner, pronouns, display name)"]
        if guilds:
            parts.append(f"leave [bold]{len(guilds)}[/] guilds")
        if relationships:
            parts.append(f"remove [bold]{len(relationships)}[/] relationships (friends, blocks, pending)")
        scope = ", ".join(parts)
        warn = f"[red]About to: {scope}. This cannot be undone.[/]"
        if not _confirm(console, warn, auto_yes):
            console.print("Aborted.")
            return

    console.print("\n[bold]Full purge:[/] Clearing profile...")
    if not dry_run:
        try:
            await client.clear_profile()
            console.print("  [green]Profile cleared[/] (avatar, banner, bio, pronouns, display name)")
        except Exception as e:
            console.print(f"  [red]Failed to clear profile: {e}[/]")
    else:
        console.print("  [yellow]Would clear profile[/]")

    # Reset nicknames in all guilds, then leave them
    console.print("\n[bold]Full purge:[/] Leaving guilds...")
    left = 0
    skipped = 0

    for guild in guilds:
        name = guild.get("name", guild["id"])

        if not dry_run:
            await client.reset_guild_nickname(guild["id"])
            success = await client.leave_guild(guild["id"])
            if success:
                left += 1
                if verbose:
                    console.print(f"    [green]Left {name}[/]")
            else:
                skipped += 1
                if verbose:
                    console.print(f"    [yellow]{name}: couldn't leave (owner?)[/]")
        else:
            left += 1
            if verbose:
                console.print(f"    [yellow]Would leave {name}[/]")

    console.print(f"  [green]{left} guilds left[/], [yellow]{skipped} skipped[/]")

    # Unfriend everyone
    console.print("\n[bold]Full purge:[/] Removing relationships...")
    removed = 0

    for rel in relationships:
        rel_user = rel.get("user", {})
        rel_name = rel_user.get("username", rel.get("id", "?"))

        if not dry_run:
            success = await client.remove_relationship(rel["id"])
            if success:
                removed += 1
                if verbose:
                    console.print(f"    [green]Removed {rel_name}[/]")
        else:
            removed += 1
            if verbose:
                console.print(f"    [yellow]Would remove {rel_name}[/]")

    console.print(f"  [green]{removed} relationships removed[/]")

    console.print("\n[bold green]Full purge complete.[/]")
    console.print(
        "  [dim]Manual steps remaining: disconnect connected accounts, "
        "deauthorize OAuth apps, remove payment methods, cancel Nitro, "
        "change email to throwaway, then delete account.[/]"
    )


def _show_status(args: argparse.Namespace) -> int:
    """Show deletion progress from the state file."""
    console = Console()
    state_path = args.state or default_state_path()

    if not state_path.exists():
        console.print(f"[yellow]No state file found at {state_path}[/]")
        return 1

    state = DeletionState(state_path)
    state.load()

    # Build channel name lookup from package if provided
    channel_names: dict[str, str] = {}
    total_in_manifest = 0
    pkg_path = args.status if isinstance(args.status, (str, Path)) and args.status is not True else None
    if pkg_path:
        try:
            pkg = parse_data_package(Path(pkg_path))
            for ch in pkg.channels:
                label = ch.channel_name
                if ch.guild_name:
                    label = f"{ch.channel_name} ({ch.guild_name})"
                channel_names[ch.channel_id] = label
            total_in_manifest = pkg.total_messages
        except (ValueError, OSError):
            pass  # no names, just show IDs

    def _label(cid: str) -> str:
        name = channel_names.get(cid)
        return name if name else cid

    console.print(f"\n[bold]Deletion progress[/] ({state_path})\n")
    console.print(f"  Messages deleted:  [green]{state.deleted_count:,}[/]")
    console.print(f"  Messages failed:   [red]{state.failed_count:,}[/]")
    if total_in_manifest:
        remaining = total_in_manifest - state.deleted_count - state.failed_count
        pct = (state.deleted_count + state.failed_count) / total_in_manifest * 100
        console.print(f"  Remaining:         {remaining:,} ({pct:.1f}% processed)")
    completed = len(state._completed_channels)
    console.print(f"  Channels complete: {completed}")

    # Show channels with most failures
    if state._failed:
        console.print(f"\n[bold]Channels with failures:[/]")
        by_count = sorted(
            state._failed.items(),
            key=lambda x: len(x[1]),
            reverse=True,
        )
        for ch_id, entries in by_count[:20]:
            console.print(f"    {_label(ch_id)}: [red]{len(entries)}[/] failed")
        if len(by_count) > 20:
            console.print(f"    ... and {len(by_count) - 20} more channels")

    return 0


def main() -> None:
    args = parse_args()

    # --status doesn't need a token
    if args.status:
        sys.exit(_show_status(args))

    token = args.token or os.environ.get("DISCORD_TOKEN")

    if not token:
        Console().print(
            "[red]Discord token required. Use --token or set DISCORD_TOKEN env var.[/]"
        )
        sys.exit(1)

    code = asyncio.run(async_main(args, token))
    sys.exit(code)

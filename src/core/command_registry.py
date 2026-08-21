"""Command definitions for Cadivor's Engineering Intelligence Command Center."""
from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Iterable
from urllib.parse import quote


@dataclass(frozen=True)
class Command:
    id: str
    title: str
    subtitle: str
    page: str
    category: str = "Navigation"
    icon: str = "→"
    keywords: tuple[str, ...] = ()
    shortcut: str = ""

    @property
    def href(self) -> str:
        return f"?page={quote(self.page)}"

    def to_dict(self) -> dict:
        payload = asdict(self)
        payload["href"] = self.href
        payload["keywords"] = list(self.keywords)
        return payload


DEFAULT_COMMANDS: tuple[Command, ...] = (
    Command("dashboard", "Open Dashboard", "Portfolio health and engineering priorities", "Dashboard", "Navigation", "⌂", ("home", "overview", "command center"), "G D"),
    Command("bom-analyzer", "Open BOM Analyzer", "Upload, analyze, and review a bill of materials", "BOM Analyzer", "Navigation", "▦", ("upload", "analysis", "bom", "parts"), "G B"),
    Command("alternative-finder", "Find Alternatives", "Search and compare replacement components", "Alternative Finder", "Engineering", "⇄", ("replacement", "substitute", "cross reference", "compare"), "G A"),
    Command("monitoring", "Open Monitoring", "Review lifecycle, stock, and supplier changes", "Monitoring", "Engineering", "◷", ("alerts", "lifecycle", "inventory", "stock", "supplier"), "G M"),
    Command("decisions", "Open Engineering Decisions", "Review approvals, rejections, and audit records", "Engineering Decisions", "Engineering", "◆", ("approve", "reject", "review", "audit", "decision"), "G E"),
    Command("reports", "Generate Engineering Report", "Executive, lifecycle, risk, and readiness reports", "Reports", "Actions", "□", ("pdf", "executive report", "export", "lifecycle report"), "G R"),
    Command("procurement", "Open Procurement Advisor", "Review sourcing and procurement recommendations", "Procurement Advisor", "Engineering", "$", ("buy", "sourcing", "supplier", "purchasing")),
    Command("portfolio", "Open Portfolio Intelligence", "Compare risk and exposure across projects", "Portfolio Intelligence", "Intelligence", "◈", ("projects", "exposure", "portfolio health")),
    Command("design-impact", "Open Design Impact Analyzer", "Estimate redesign scope and engineering impact", "Design Impact Analyzer", "Intelligence", "◇", ("redesign", "footprint", "compatibility", "effort")),
    Command("cost-optimization", "Open Cost Optimization", "Identify cost reduction opportunities", "Cost Optimization", "Intelligence", "$", ("savings", "price", "cost")),
    Command("supply-scenario", "Run Supply Risk Scenario", "Simulate supplier and inventory disruptions", "Supply Risk Scenario", "Intelligence", "△", ("simulate", "what if", "disruption", "supplier disappears")),
    Command("workspace", "Open Workspace", "Manage teams, members, and organization activity", "Workspace", "Workspace", "●", ("team", "organization", "members", "collaboration")),
    Command("notifications", "Open Notifications", "Review workspace and monitoring updates", "Notifications", "Workspace", "●", ("alerts", "updates", "changes")),
    Command("pricing", "Open Pricing", "Compare Cadivor plans and entitlements", "Pricing", "Account", "$", ("upgrade", "billing", "subscription", "plan")),
    Command("settings", "Open Settings", "Profile, account, and application settings", "Settings", "Account", "⚙", ("profile", "preferences", "account")),
    Command("help", "Open Help", "Cadivor guidance and support", "Help", "Support", "?", ("documentation", "support", "how to")),
    Command("about", "About Cadivor", "Product information and mission", "About", "Support", "C", ("company", "version")),
)


def command_payload(commands: Iterable[Command] = DEFAULT_COMMANDS, dynamic_commands: Iterable[dict] = ()) -> list[dict]:
    """Return static navigation plus workspace-aware searchable records."""
    payload = [command.to_dict() for command in commands]
    payload.extend(dict(command) for command in dynamic_commands)
    return payload

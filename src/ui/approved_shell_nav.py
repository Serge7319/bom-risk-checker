"""One authenticated navigation rail. NAV_GROUPS stays the stable product map for tests.

Every signed-in route renders the same groups, order, and destinations.
Only the active item changes. Engineering Intelligence report tabs stay on that page.
"""

from __future__ import annotations


# Label, widget slug, destination. Order is the rail order on every route.
SHARED_NAV_GROUPS = (
    ("Workspace", (
        ("Home", "home", "Dashboard"),
        ("BOM Analyzer", "bom-analyzer", "BOM Analyzer"),
        ("Engineering Decisions", "engineering-decisions", "Engineering Decisions"),
        ("Monitoring", "monitoring", "Monitoring"),
        ("Find a replacement", "find-replacement", "Alternative Finder"),
        ("Reports", "reports", "Reports"),
    )),
    ("Decision Tools", (
        ("Compare Parts", "compare-parts", "Compare Parts"),
        ("Datasheet Q&A", "datasheet-qa", "Datasheet Q&A"),
        ("Procurement Advisor", "procurement", "Procurement Advisor"),
        ("Design Impact Analyzer", "design-impact", "Design Impact Analyzer"),
        ("Cost Optimization", "cost", "Cost Optimization"),
        ("Supply Risk Scenario", "supply-scenario", "Supply Risk Scenario"),
    )),
    ("Intelligence", (
        ("Settings", "settings", "Settings"),
        ("Portfolio Intelligence", "portfolio", "Portfolio Intelligence"),
        ("Detailed Risk Report", "detailed-risk", "Analysis Details"),
        ("Engineering Intelligence", "engineering-intelligence", "Analysis Details"),
    )),
)


def shared_nav_groups() -> tuple:
    """Return the single rail used by every authenticated route."""
    return SHARED_NAV_GROUPS


def nav_groups_for_page(page: str) -> tuple | None:
    """Page shells are retired. The shared rail does not change with the route."""
    return None


def active_nav_label(page: str, *, detailed_risk: bool = False) -> str:
    if page == "Analysis Details":
        return "Detailed Risk Report" if detailed_risk else "Engineering Intelligence"
    for _group, rows in SHARED_NAV_GROUPS:
        for label, _slug, destination in rows:
            if destination == page:
                return label
    return ""


def top_nav_items() -> tuple:
    """Kept for callers. The shell no longer replaces the rail with this bar."""
    return ()


def uses_top_nav(page: str, *, analysis_tab: str = "", detailed_risk: bool = False) -> bool:
    """Report tabs stay inside Engineering Intelligence. They never replace the rail."""
    return False


_ACTIVE = {
    "Dashboard": "Home",
    "BOM Analyzer": "BOMs",
    "Engineering Decisions": "Engineering Decisions",
    "Monitoring": "Alerts & Monitoring",
    "Reports": "Reports",
    "Alternative Finder": "Find a replacement",
    "Compare Parts": "Compare parts",
    "Datasheet Q&A": "Datasheet Q&A",
    "Design Impact Analyzer": "Design Impact",
    "Procurement Advisor": "Procurement Advisor",
    "Cost Optimization": "Cost Optimization",
    "Supply Risk Scenario": "Supply Scenario",
    "Portfolio Intelligence": "Portfolio Intelligence",
    "Settings": "Settings",
    "Analysis Details": "Risk Analysis",
}


_SHELLS = {
    "Dashboard": (
        ("", (
            ("Home", "dashboard", "Dashboard"),
            ("BOM Analysis", "bom", "BOM Analyzer"),
            ("Parts Intelligence", "alternatives", "Alternative Finder"),
            ("Suppliers", "procurement", "Procurement Advisor"),
            ("Reports", "reports", "Reports"),
        )),
        ("Library", (
            ("Saved BOMs", "saved-boms", "BOM Analyzer"),
            ("Watchlist", "monitoring", "Monitoring"),
            ("Custom Rules", "settings", "Settings"),
        )),
        ("Admin", (
            ("Workspace Settings", "workspace-settings", "Settings"),
            ("Integrations", "integrations", "Settings"),
        )),
    ),
    "BOM Analyzer": (
        ("Main", (
            ("Dashboard", "dashboard", "Dashboard"),
            ("Projects", "projects", "Portfolio Intelligence"),
            ("BOMs", "bom", "BOM Analyzer"),
            ("Parts", "alternatives", "Alternative Finder"),
            ("Suppliers", "procurement", "Procurement Advisor"),
            ("Compliance", "decisions", "Engineering Decisions"),
        )),
        ("Insights", (
            ("Risk Analysis", "impact", "Design Impact Analyzer"),
            ("Alternatives", "compare", "Compare Parts"),
            ("Reports", "reports", "Reports"),
        )),
        ("Manage", (
            ("Integrations", "integrations", "Settings"),
            ("Workspace Settings", "settings", "Settings"),
        )),
    ),
    "Engineering Decisions": (
        ("Planning", (
            ("Dashboard", "dashboard", "Dashboard"),
            ("Projects", "projects", "Portfolio Intelligence"),
            ("BOMs", "bom", "BOM Analyzer"),
            ("Components", "alternatives", "Alternative Finder"),
            ("Suppliers", "procurement", "Procurement Advisor"),
        )),
        ("Engineering", (
            ("Engineering Decisions", "decisions", "Engineering Decisions"),
            ("Change Requests", "monitoring", "Monitoring"),
            ("Design Reviews", "impact", "Design Impact Analyzer"),
            ("Compliance", "portfolio", "Portfolio Intelligence"),
            ("Reports", "reports", "Reports"),
        )),
        ("Settings", (
            ("Workspace", "settings", "Settings"),
            ("Integrations", "integrations", "Settings"),
            ("Team", "team", "Settings"),
            ("Preferences", "preferences", "Settings"),
        )),
    ),
    "Monitoring": (
        ("Discover", (
            ("Dashboard", "dashboard", "Dashboard"),
            ("Search", "alternatives", "Alternative Finder"),
            ("Parts & BOMs", "bom", "BOM Analyzer"),
            ("Suppliers", "procurement", "Procurement Advisor"),
        )),
        ("Monitor", (
            ("Alerts & Monitoring", "monitoring", "Monitoring"),
            ("Watchlists", "watchlists", "Monitoring"),
            ("Saved Searches", "saved-searches", "Alternative Finder"),
        )),
        ("Analyze", (
            ("Reports", "reports", "Reports"),
            ("Market intelligence", "portfolio", "Portfolio Intelligence"),
        )),
        ("Manage", (
            ("Projects", "projects", "Portfolio Intelligence"),
            ("Team", "team", "Settings"),
            ("Settings", "settings", "Settings"),
        )),
    ),
    "Reports": (
        ("Analyze", (
            ("Dashboard", "dashboard", "Dashboard"),
            ("BOM Analysis", "bom", "BOM Analyzer"),
            ("Part Intelligence", "alternatives", "Alternative Finder"),
            ("Risk Assessment", "impact", "Design Impact Analyzer"),
        )),
        ("Plan", (
            ("Scenarios", "scenario", "Supply Risk Scenario"),
            ("Sourcing", "procurement", "Procurement Advisor"),
        )),
        ("Report", (
            ("Reports", "reports", "Reports"),
        )),
        ("Manage", (
            ("Libraries", "compare", "Compare Parts"),
            ("Settings", "settings", "Settings"),
        )),
    ),
    "Alternative Finder": (
        ("Analyze", (
            ("Dashboard", "dashboard", "Dashboard"),
            ("BOM Intelligence", "bom", "BOM Analyzer"),
            ("Part Insights", "compare", "Compare Parts"),
            ("Find a replacement", "alternatives", "Alternative Finder"),
            ("Datasheet Q&A", "datasheet-qa", "Datasheet Q&A"),
        )),
        ("Manage", (
            ("Parts Library", "parts-library", "Compare Parts"),
            ("Suppliers", "procurement", "Procurement Advisor"),
            ("Projects", "projects", "Portfolio Intelligence"),
            ("Watchlist", "monitoring", "Monitoring"),
        )),
        ("Configure", (
            ("Integrations", "integrations", "Settings"),
            ("Settings", "settings", "Settings"),
        )),
    ),
    "Compare Parts": (
        ("Discover", (
            ("Search", "alternatives", "Alternative Finder"),
            ("Parts library", "parts-library", "Compare Parts"),
            ("Compare parts", "compare", "Compare Parts"),
            ("BOM tools", "bom", "BOM Analyzer"),
            ("Alerts", "monitoring", "Monitoring"),
        )),
        ("Build", (
            ("Projects", "projects", "Portfolio Intelligence"),
            ("BOMs", "boms", "BOM Analyzer"),
            ("Design notes", "impact", "Design Impact Analyzer"),
            ("Exports", "reports", "Reports"),
        )),
        ("Manage", (
            ("Suppliers", "procurement", "Procurement Advisor"),
            ("Categories", "portfolio", "Portfolio Intelligence"),
            ("Settings", "settings", "Settings"),
        )),
    ),
    "Datasheet Q&A": (
        ("Home", (
            ("Dashboard", "dashboard", "Dashboard"),
            ("Projects", "projects", "Portfolio Intelligence"),
            ("Parts Library", "alternatives", "Alternative Finder"),
            ("Watchlist", "monitoring", "Monitoring"),
        )),
        ("AI Tools", (
            ("Datasheet Q&A", "datasheet-qa", "Datasheet Q&A"),
            ("Document Analysis", "document-analysis", "Datasheet Q&A"),
            ("Parts Comparison", "compare", "Compare Parts"),
            ("Design Assistant", "impact", "Design Impact Analyzer"),
        )),
        ("Resources", (
            ("Component Search", "component-search", "Alternative Finder"),
            ("Manufacturer Library", "procurement", "Procurement Advisor"),
            ("Technical Articles", "reports", "Reports"),
        )),
        ("Settings", (
            ("Workspace Settings", "settings", "Settings"),
            ("Help & Support", "help", "Help"),
        )),
    ),
    "Procurement Advisor": (
        ("Overview", (
            ("Home", "dashboard", "Dashboard"),
            ("Parts & BOMs", "bom", "BOM Analyzer"),
            ("Projects", "projects", "Portfolio Intelligence"),
            ("Analytics", "portfolio", "Portfolio Intelligence"),
        )),
        ("Engineering Tools", (
            ("Design Advisor", "impact", "Design Impact Analyzer"),
            ("Compliance Checker", "decisions", "Engineering Decisions"),
            ("Cost Estimator", "cost", "Cost Optimization"),
            ("Procurement Advisor", "procurement", "Procurement Advisor"),
            ("Lifecycle Insights", "monitoring", "Monitoring"),
        )),
        ("Manage", (
            ("Suppliers", "suppliers", "Procurement Advisor"),
            ("Libraries", "compare", "Compare Parts"),
            ("Settings", "settings", "Settings"),
        )),
    ),
    "Design Impact Analyzer": (
        ("Overview", (
            ("Home", "dashboard", "Dashboard"),
            ("Components", "alternatives", "Alternative Finder"),
            ("Projects", "projects", "Portfolio Intelligence"),
            ("BOMs", "bom", "BOM Analyzer"),
            ("Supply Chain", "scenario", "Supply Risk Scenario"),
        )),
        ("Analysis", (
            ("Design Impact", "impact", "Design Impact Analyzer"),
            ("Risk Monitor", "monitoring", "Monitoring"),
            ("Alternatives", "compare", "Compare Parts"),
        )),
        ("Library", (
            ("Parts Database", "parts-database", "Alternative Finder"),
            ("Suppliers", "procurement", "Procurement Advisor"),
        )),
        ("Settings", (
            ("Workspace Settings", "settings", "Settings"),
            ("Help & Support", "help", "Help"),
        )),
    ),
    "Cost Optimization": (
        ("Workspace", (
            ("Dashboard", "dashboard", "Dashboard"),
            ("Parts & BOMs", "bom", "BOM Analyzer"),
            ("Suppliers", "procurement", "Procurement Advisor"),
            ("Cost Optimization", "cost", "Cost Optimization"),
            ("Design Insights", "impact", "Design Impact Analyzer"),
            ("Risk & Supply", "scenario", "Supply Risk Scenario"),
            ("Sustainability", "portfolio", "Portfolio Intelligence"),
            ("Reports", "reports", "Reports"),
        )),
        ("Library", (
            ("Library", "compare", "Compare Parts"),
            ("Settings", "settings", "Settings"),
        )),
    ),
    "Supply Risk Scenario": (
        ("Dashboard", (
            ("Home", "dashboard", "Dashboard"),
            ("Insights", "portfolio", "Portfolio Intelligence"),
            ("Alerts", "monitoring", "Monitoring"),
        )),
        ("Engineering", (
            ("Components", "alternatives", "Alternative Finder"),
            ("BOMs", "bom", "BOM Analyzer"),
            ("Design intelligence", "impact", "Design Impact Analyzer"),
        )),
        ("Supply Chain", (
            ("Supply Scenario", "scenario", "Supply Risk Scenario"),
            ("Suppliers", "procurement", "Procurement Advisor"),
            ("Risk Monitor", "risk-monitor", "Monitoring"),
            ("Alternatives", "compare", "Compare Parts"),
        )),
        ("Admin", (
            ("Workspace", "settings", "Settings"),
            ("Integrations", "integrations", "Settings"),
            ("Settings", "workspace-settings", "Settings"),
        )),
    ),
    "Portfolio Intelligence": (
        ("Analyze", (
            ("Portfolio Intelligence", "portfolio", "Portfolio Intelligence"),
            ("Component Explorer", "alternatives", "Alternative Finder"),
            ("Risk Analysis", "impact", "Design Impact Analyzer"),
            ("Lifecycle Monitoring", "monitoring", "Monitoring"),
        )),
        ("Manage", (
            ("Projects", "projects", "Portfolio Intelligence"),
            ("BOMs", "bom", "BOM Analyzer"),
            ("Components", "compare", "Compare Parts"),
            ("Suppliers", "procurement", "Procurement Advisor"),
        )),
        ("Share", (
            ("Shared Components", "shared", "Compare Parts"),
            ("Reports", "reports", "Reports"),
        )),
        ("", (
            ("Settings", "settings", "Settings"),
        )),
    ),
    "Settings": (
        ("Analyze", (
            ("Dashboard", "dashboard", "Dashboard"),
            ("Projects", "projects", "Portfolio Intelligence"),
            ("Components", "alternatives", "Alternative Finder"),
            ("Simulations", "scenario", "Supply Risk Scenario"),
            ("Reports", "reports", "Reports"),
        )),
        ("Library", (
            ("Materials", "compare", "Compare Parts"),
            ("Standards", "decisions", "Engineering Decisions"),
            ("Templates", "reports-templates", "Reports"),
        )),
        ("Team", (
            ("Members", "members", "Settings"),
            ("Activity", "monitoring", "Monitoring"),
            ("Integrations", "integrations", "Settings"),
            ("Settings", "settings", "Settings"),
        )),
    ),
    "Analysis Details": (
        ("", (
            ("Home", "dashboard", "Dashboard"),
            ("BOMs", "bom", "BOM Analyzer"),
            ("Risk Analysis", "impact", "Design Impact Analyzer"),
            ("Parts Search", "alternatives", "Alternative Finder"),
            ("Suppliers", "procurement", "Procurement Advisor"),
            ("Reports", "reports", "Reports"),
        )),
        ("", (
            ("Settings", "settings", "Settings"),
            ("Help & Support", "help", "Help"),
        )),
    ),
}

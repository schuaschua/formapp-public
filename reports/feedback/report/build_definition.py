"""Build the Power BI report definition (PBIR) for the AI feedback report (Story 7.4, AD-20).

Writes reports/feedback/report/definition/ as PBIR JSON files: one page with cards, a trend, the
category breakdown, a category x product matrix, the comments table and three slicers, all on the
`feedback` table and the measures in ../measures.dax. Run it after changing the layout; commit the
generated files. `deploy_report.py` uploads them.
"""

import json
from pathlib import Path

HERE = Path(__file__).parent
OUT = HERE / "definition"
SCHEMA = "https://developer.microsoft.com/json-schemas/fabric/item/report/definition"
PAGE = "aifeedbackpage00001"
TABLE = "feedback"


def col(name: str) -> dict:
    return {
        "field": {"Column": {"Expression": {"SourceRef": {"Entity": TABLE}}, "Property": name}},
        "queryRef": f"{TABLE}.{name}",
        "nativeQueryRef": name,
    }


def measure(name: str) -> dict:
    return {
        "field": {"Measure": {"Expression": {"SourceRef": {"Entity": TABLE}}, "Property": name}},
        "queryRef": f"{TABLE}.{name}",
        "nativeQueryRef": name,
    }


def title(text: str) -> dict:
    return {
        "title": [
            {
                "properties": {
                    "show": {"expr": {"Literal": {"Value": "true"}}},
                    "text": {"expr": {"Literal": {"Value": f"'{text}'"}}},
                }
            }
        ]
    }


# (id, visualType, x, y, width, height, {role: [projections]}, title)
VISUALS = [
    ("card0avgrating000001", "card", 200, 10, 250, 110, {"Values": [measure("Average rating")]}, "Average rating"),
    ("card0count000000002", "card", 470, 10, 250, 110, {"Values": [measure("Feedback count")]}, "Feedback"),
    ("card0lowshare000003", "card", 740, 10, 250, 110, {"Values": [measure("Low rating share")]}, "Rated 1-2"),
    ("card0praise00000004", "card", 1010, 10, 250, 110, {"Values": [measure("Praise share")]}, "Praise share of comments"),
    ("line0trend000000005", "lineChart", 200, 130, 530, 250,
     {"Category": [col("submitted_date")], "Y": [measure("Average rating")]}, "Average rating over time"),
    ("bar0category0000006", "clusteredBarChart", 740, 130, 520, 250,
     {"Category": [col("category")], "Y": [measure("Feedback count")]}, "Feedback by category"),
    ("matrix0catprod00007", "pivotTable", 200, 390, 530, 320,
     {"Rows": [col("category")], "Columns": [col("product_code")], "Values": [measure("Average rating")]},
     "Average rating by category and product"),
    ("table0comments00008", "tableEx", 740, 390, 520, 320,
     {"Values": [col("submitted_date"), col("product_code"), col("rating"), col("category"), col("comment")]},
     "Comments"),
    ("slicer0category0009", "slicer", 10, 10, 180, 230, {"Values": [col("category")]}, "Category"),
    ("slicer0product00010", "slicer", 10, 250, 180, 200, {"Values": [col("product_code")]}, "Product"),
    ("slicer0date00000011", "slicer", 10, 460, 180, 250, {"Values": [col("submitted_date")]}, "Submitted"),
]


def write(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2) + "\n")


def main() -> None:
    write(OUT / "version.json", {"$schema": f"{SCHEMA}/versionMetadata/1.0.0/schema.json", "version": "2.0.0"})
    write(
        OUT / "report.json",
        {
            "$schema": f"{SCHEMA}/report/3.1.0/schema.json",
            "themeCollection": {
                "baseTheme": {
                    "name": "CY25SU12",
                    "reportVersionAtImport": {"visual": "2.5.0", "report": "3.1.0", "page": "2.3.0"},
                    "type": "SharedResources",
                }
            },
            "resourcePackages": [
                {
                    "name": "SharedResources",
                    "type": "SharedResources",
                    "items": [{"name": "CY25SU12", "path": "BaseThemes/CY25SU12.json", "type": "BaseTheme"}],
                }
            ],
            "settings": {"useStylableVisualContainerHeader": True, "defaultDrillFilterOtherVisuals": True},
        },
    )
    write(
        OUT / "pages" / "pages.json",
        {"$schema": f"{SCHEMA}/pagesMetadata/1.0.0/schema.json", "pageOrder": [PAGE], "activePageName": PAGE},
    )
    write(
        OUT / "pages" / PAGE / "page.json",
        {
            "$schema": f"{SCHEMA}/page/2.0.0/schema.json",
            "name": PAGE,
            "displayName": "AI feedback",
            "displayOption": "FitToPage",
            "height": 720,
            "width": 1280,
        },
    )
    for z, (name, vtype, x, y, w, h, roles, text) in enumerate(VISUALS, start=1):
        visual: dict = {
            "visualType": vtype,
            "query": {"queryState": {role: {"projections": projs} for role, projs in roles.items()}},
            "visualContainerObjects": title(text),
            "drillFilterOtherVisuals": True,
        }
        if vtype == "tableEx":
            visual["query"]["sortDefinition"] = {
                "sort": [{"field": col("submitted_date")["field"], "direction": "Descending"}]
            }
        write(
            OUT / "pages" / PAGE / "visuals" / name / "visual.json",
            {
                "$schema": f"{SCHEMA}/visualContainer/2.0.0/schema.json",
                "name": name,
                "position": {"x": x, "y": y, "z": z * 1000, "width": w, "height": h, "tabOrder": z * 1000},
                "visual": visual,
            },
        )


if __name__ == "__main__":
    main()

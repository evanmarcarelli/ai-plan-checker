import io
import csv
from typing import Optional
from datetime import datetime
from reportlab.lib.pagesizes import letter, A4
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import inch
from reportlab.lib import colors
from reportlab.platypus import (
    SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle,
    HRFlowable, PageBreak
)
from reportlab.lib.enums import TA_CENTER, TA_LEFT, TA_RIGHT
from app.models.schemas import ComplianceReport, ComplianceStatus
from app.utils.logger import get_logger

logger = get_logger(__name__)

STATUS_COLORS = {
    "compliant": colors.HexColor("#16a34a"),
    "non_compliant": colors.HexColor("#dc2626"),
    "needs_review": colors.HexColor("#d97706"),
    "not_applicable": colors.HexColor("#6b7280"),
}

SEVERITY_COLORS = {
    "critical": colors.HexColor("#dc2626"),
    "high": colors.HexColor("#ea580c"),
    "medium": colors.HexColor("#d97706"),
    "low": colors.HexColor("#16a34a"),
}


class ExportService:

    def export_pdf(self, report: ComplianceReport) -> bytes:
        """Generate a formatted PDF compliance report."""
        buffer = io.BytesIO()
        doc = SimpleDocTemplate(
            buffer,
            pagesize=letter,
            rightMargin=0.75 * inch,
            leftMargin=0.75 * inch,
            topMargin=0.75 * inch,
            bottomMargin=0.75 * inch,
        )

        styles = getSampleStyleSheet()
        story = []

        # Custom styles
        title_style = ParagraphStyle(
            "CustomTitle",
            parent=styles["Title"],
            fontSize=24,
            textColor=colors.HexColor("#1e293b"),
            spaceAfter=6,
        )
        heading_style = ParagraphStyle(
            "CustomHeading",
            parent=styles["Heading1"],
            fontSize=14,
            textColor=colors.HexColor("#1e40af"),
            spaceBefore=12,
            spaceAfter=6,
        )
        body_style = ParagraphStyle(
            "CustomBody",
            parent=styles["Normal"],
            fontSize=9,
            textColor=colors.HexColor("#374151"),
            spaceAfter=4,
        )
        small_style = ParagraphStyle(
            "Small",
            parent=styles["Normal"],
            fontSize=8,
            textColor=colors.HexColor("#6b7280"),
        )

        # ---- Header ----
        story.append(Paragraph("AI PLAN CHECKER", title_style))
        story.append(Paragraph("Building Code Compliance Report", heading_style))
        story.append(HRFlowable(width="100%", thickness=2, color=colors.HexColor("#1e40af")))
        story.append(Spacer(1, 12))

        # ---- Project Info ----
        j = report.jurisdiction
        pd = report.plan_data
        info_data = [
            ["Report ID:", report.report_id or "N/A"],
            ["Generated:", report.generated_at.strftime("%Y-%m-%d %H:%M UTC") if report.generated_at else "N/A"],
            ["Project:", pd.project_name or "Unknown Project" if pd else "Unknown"],
            ["Address:", pd.project_address or "Unknown" if pd else "Unknown"],
            ["Jurisdiction:", f"{j.city or ''}, {j.state or ''} {j.state_code or ''}".strip(", ") if j else "Unknown"],
            ["Plan Type:", pd.plan_type.value.title() if pd else "Unknown"],
            ["Code Version:", list(report.code_versions.values())[0] if report.code_versions else "IBC 2021"],
        ]

        info_table = Table(info_data, colWidths=[1.5 * inch, 5 * inch])
        info_table.setStyle(TableStyle([
            ("FONTNAME", (0, 0), (0, -1), "Helvetica-Bold"),
            ("FONTSIZE", (0, 0), (-1, -1), 9),
            ("TEXTCOLOR", (0, 0), (0, -1), colors.HexColor("#1e293b")),
            ("TEXTCOLOR", (1, 0), (1, -1), colors.HexColor("#374151")),
            ("TOPPADDING", (0, 0), (-1, -1), 3),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
        ]))
        story.append(info_table)
        story.append(Spacer(1, 16))

        # ---- Summary Box ----
        s = report.summary
        score_pct = f"{s.compliance_score:.0%}"
        summary_data = [
            ["COMPLIANCE SCORE", "TOTAL CHECKS", "✓ COMPLIANT", "✗ NON-COMPLIANT", "⚠ NEEDS REVIEW"],
            [score_pct, str(s.total_checks), str(s.compliant), str(s.non_compliant), str(s.needs_review)],
        ]
        summary_table = Table(summary_data, colWidths=[1.4 * inch] * 5)
        summary_table.setStyle(TableStyle([
            ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#1e293b")),
            ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
            ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
            ("FONTSIZE", (0, 0), (-1, 0), 8),
            ("ALIGN", (0, 0), (-1, -1), "CENTER"),
            ("FONTNAME", (0, 1), (-1, 1), "Helvetica-Bold"),
            ("FONTSIZE", (0, 1), (0, 1), 18),
            ("FONTSIZE", (1, 1), (-1, 1), 14),
            ("TEXTCOLOR", (0, 1), (0, 1), colors.HexColor("#1e40af")),
            ("TEXTCOLOR", (2, 1), (2, 1), colors.HexColor("#16a34a")),
            ("TEXTCOLOR", (3, 1), (3, 1), colors.HexColor("#dc2626")),
            ("TEXTCOLOR", (4, 1), (4, 1), colors.HexColor("#d97706")),
            ("BOX", (0, 0), (-1, -1), 1, colors.HexColor("#e2e8f0")),
            ("INNERGRID", (0, 0), (-1, -1), 0.5, colors.HexColor("#e2e8f0")),
            ("TOPPADDING", (0, 0), (-1, -1), 8),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 8),
        ]))
        story.append(summary_table)
        story.append(Spacer(1, 20))

        # ---- Findings ----
        story.append(Paragraph("COMPLIANCE FINDINGS", heading_style))
        story.append(HRFlowable(width="100%", thickness=1, color=colors.HexColor("#e2e8f0")))
        story.append(Spacer(1, 8))

        # Table header
        findings_header = [["Code", "Description", "Status", "Plan Value", "Required", "Sev."]]
        findings_rows = []
        for f in report.findings:
            req = f.code_requirement
            status_text = f.status.value.replace("_", " ").title()
            row = [
                f"{req.section}",
                Paragraph(f.description[:100], small_style),
                status_text,
                f.plan_value or "—",
                f.required_value or "—",
                f.severity[:4].upper(),
            ]
            findings_rows.append(row)

        if findings_rows:
            all_rows = findings_header + findings_rows
            findings_table = Table(
                all_rows,
                colWidths=[0.8 * inch, 2.8 * inch, 1.0 * inch, 0.9 * inch, 0.9 * inch, 0.5 * inch]
            )

            table_style = [
                ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#1e293b")),
                ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
                ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
                ("FONTSIZE", (0, 0), (-1, -1), 8),
                ("ALIGN", (0, 0), (-1, -1), "LEFT"),
                ("ALIGN", (2, 0), (2, -1), "CENTER"),
                ("ALIGN", (5, 0), (5, -1), "CENTER"),
                ("BOX", (0, 0), (-1, -1), 1, colors.HexColor("#e2e8f0")),
                ("INNERGRID", (0, 0), (-1, -1), 0.3, colors.HexColor("#e2e8f0")),
                ("TOPPADDING", (0, 0), (-1, -1), 4),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
                ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#f8fafc")]),
            ]

            # Color status cells
            for i, f in enumerate(report.findings, 1):
                status_color = STATUS_COLORS.get(f.status.value, colors.gray)
                table_style.append(("TEXTCOLOR", (2, i), (2, i), status_color))
                table_style.append(("FONTNAME", (2, i), (2, i), "Helvetica-Bold"))
                sev_color = SEVERITY_COLORS.get(f.severity, colors.gray)
                table_style.append(("TEXTCOLOR", (5, i), (5, i), sev_color))
                table_style.append(("FONTNAME", (5, i), (5, i), "Helvetica-Bold"))

            findings_table.setStyle(TableStyle(table_style))
            story.append(findings_table)

        story.append(Spacer(1, 20))

        # ---- Corrections Required (full, itemized, per-finding) ----
        # The findings table above is a compact overview. Contractors need the
        # COMPLETE list of what to fix, with the specific correction for each
        # item — that's the whole point of the export. We list every finding
        # that isn't already compliant/not-applicable, untruncated, and never
        # cap the count.
        actionable = [
            f for f in report.findings
            if f.status.value in ("non_compliant", "needs_review")
        ]
        if actionable:
            correction_head_style = ParagraphStyle(
                "CorrectionHead",
                parent=body_style,
                fontSize=10,
                fontName="Helvetica-Bold",
                textColor=colors.HexColor("#1e293b"),
                spaceBefore=6,
                spaceAfter=2,
            )
            story.append(Paragraph(
                f"CORRECTIONS REQUIRED ({len(actionable)})", heading_style
            ))
            story.append(HRFlowable(width="100%", thickness=1, color=colors.HexColor("#e2e8f0")))
            story.append(Spacer(1, 8))
            for idx, f in enumerate(actionable, 1):
                req = f.code_requirement
                ref = req.section or req.code_id or "—"
                sev = (f.severity or "").upper()
                status_text = f.status.value.replace("_", " ").title()
                story.append(Paragraph(
                    f"{idx}. [{sev}] {ref} — {status_text}", correction_head_style
                ))
                if f.description:
                    story.append(Paragraph(f.description, body_style))
                if f.plan_value or f.required_value:
                    story.append(Paragraph(
                        f"<b>Plan shows:</b> {f.plan_value or '—'} &nbsp;&nbsp;"
                        f"<b>Required:</b> {f.required_value or '—'}",
                        small_style,
                    ))
                if f.recommendation:
                    story.append(Paragraph(f"<b>Correction:</b> {f.recommendation}", body_style))
                story.append(Spacer(1, 6))
            story.append(Spacer(1, 14))

        # ---- Additional Recommendations ----
        # Report-level recommendations beyond the per-finding corrections above.
        # No longer capped at 15 — the prior [:15] slice silently dropped
        # corrections off the end of the document.
        if report.recommendations:
            story.append(Paragraph("ADDITIONAL RECOMMENDATIONS", heading_style))
            story.append(HRFlowable(width="100%", thickness=1, color=colors.HexColor("#e2e8f0")))
            story.append(Spacer(1, 8))
            for rec in report.recommendations:
                story.append(Paragraph(f"• {rec}", body_style))

        story.append(Spacer(1, 20))
        story.append(Paragraph(
            f"Generated by AI Plan Checker v2.0 | {datetime.utcnow().strftime('%Y-%m-%d')} | "
            f"This report is for informational purposes only. Always consult the AHJ.",
            small_style
        ))

        # Insert disclaimer block at top of story (before content)
        disclaimer_text = (
            "<b>AI-GENERATED PRELIMINARY REVIEW.</b> This report is produced by an AI system for "
            "educational and pre-submittal feedback only. It is <b>not engineering advice</b> and does "
            "<b>not replace</b> stamped review by a licensed architect or engineer or approval by the "
            "Authority Having Jurisdiction (AHJ). Architechtura makes no warranty of accuracy and is not liable "
            "for any decision, permit outcome, construction activity, or damages arising from reliance on "
            "this output. Always verify all findings with a licensed professional and your AHJ before "
            "submitting or constructing."
        )
        disclaimer_style = ParagraphStyle(
            "Disclaimer",
            parent=styles["Normal"],
            fontSize=8,
            textColor=colors.HexColor("#92400e"),
            backColor=colors.HexColor("#fef3c7"),
            borderColor=colors.HexColor("#f59e0b"),
            borderWidth=1,
            borderPadding=8,
            spaceAfter=12,
            leading=11,
        )
        story.insert(0, Paragraph(disclaimer_text, disclaimer_style))

        def _watermark(canvas, doc_obj):
            """Add 'AI-generated preliminary review' watermark + page number to every page."""
            canvas.saveState()
            # Top right watermark
            canvas.setFillColor(colors.HexColor("#9ca3af"))
            canvas.setFont("Helvetica-Oblique", 7)
            canvas.drawRightString(
                letter[0] - 0.5 * inch,
                letter[1] - 0.35 * inch,
                "AI-generated preliminary review — not official approval",
            )
            # Bottom: page number + brand
            canvas.setFont("Helvetica", 7)
            canvas.setFillColor(colors.HexColor("#6b7280"))
            canvas.drawString(0.5 * inch, 0.35 * inch, "Architechtura · AI Plan Checker")
            canvas.drawRightString(
                letter[0] - 0.5 * inch,
                0.35 * inch,
                f"Page {doc_obj.page}",
            )
            # Diagonal faint watermark across the page
            canvas.saveState()
            canvas.translate(letter[0] / 2, letter[1] / 2)
            canvas.rotate(45)
            canvas.setFillColor(colors.HexColor("#f3f4f6"))
            canvas.setFont("Helvetica-Bold", 60)
            canvas.drawCentredString(0, 0, "PRELIMINARY")
            canvas.restoreState()
            canvas.restoreState()

        doc.build(story, onFirstPage=_watermark, onLaterPages=_watermark)
        return buffer.getvalue()

    def export_csv(self, report: ComplianceReport) -> str:
        """Generate CSV compliance report."""
        output = io.StringIO()
        writer = csv.writer(output)

        # Header info
        writer.writerow(["AI Plan Checker - Compliance Report"])
        writer.writerow(["Generated", report.generated_at.isoformat() if report.generated_at else ""])
        writer.writerow(["Report ID", report.report_id])
        if report.jurisdiction:
            j = report.jurisdiction
            writer.writerow(["Jurisdiction", f"{j.city}, {j.state}"])
        writer.writerow(["Compliance Score", f"{report.summary.compliance_score:.0%}"])
        writer.writerow([])

        # Summary
        writer.writerow(["SUMMARY"])
        writer.writerow(["Total Checks", report.summary.total_checks])
        writer.writerow(["Compliant", report.summary.compliant])
        writer.writerow(["Non-Compliant", report.summary.non_compliant])
        writer.writerow(["Needs Review", report.summary.needs_review])
        writer.writerow(["Critical Issues", report.summary.critical_issues])
        writer.writerow([])

        # Findings
        writer.writerow([
            "Code ID", "Code Name", "Section", "Category",
            "Status", "Severity", "Plan Value", "Required Value",
            "Description", "Recommendation"
        ])

        for f in report.findings:
            req = f.code_requirement
            writer.writerow([
                req.code_id,
                req.code_name,
                req.section,
                req.category,
                f.status.value,
                f.severity,
                f.plan_value or "",
                f.required_value or "",
                f.description,
                f.recommendation or "",
            ])

        # Report-level recommendations, so the CSV carries the same complete
        # set of corrections as the PDF (the per-finding Recommendation column
        # above already covers item-by-item fixes).
        if report.recommendations:
            writer.writerow([])
            writer.writerow(["RECOMMENDATIONS"])
            for rec in report.recommendations:
                writer.writerow([rec])

        return output.getvalue()


export_service = ExportService()

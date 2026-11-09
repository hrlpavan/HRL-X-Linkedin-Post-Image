#!/usr/bin/env python3
"""
HRL × LinkedIn Post Image Generator
Official Apple-Grade Light-Theme Card Renderer for HRL International Private Limited.

Design Principles:
1. HRL Tactile Identity Card Design Language (Light Theme) + Apple Cupertino Typography (SF Pro & SF Mono).
2. 2x Retina Supersampling (renders at 2800x1800, downsamples via LANCZOS to 1400x900 for zero aliasing).
3. Context-Aware Brand Themes:
   - 'gitlab-orange' (Default for GitLab posts): GitLab Tanuki Orange (#FC6D26 / #E24329 / #FCA326)
   - 'hrl-rose': HRL Signature Rose-Crimson (#E05375 / #D1002D)
4. Clean Executive Footer: Never prints raw URLs in the footer.
"""
import argparse
import json
import os
from PIL import Image, ImageDraw, ImageFilter, ImageFont

THEMES = {
    "gitlab-orange": {
        "name": "GitLab Tanuki Orange (Apple Light Mode)",
        "canvas_top": (252, 250, 248),
        "canvas_bottom": (255, 244, 236),
        "shadow_tint": (226, 67, 41, 28),
        "card_border": (245, 212, 192, 255),
        "stripe_top": (226, 67, 41),      # GitLab Deep Orange #E24329
        "stripe_bottom": (252, 109, 38),  # GitLab Tanuki Orange #FC6D26
        "pill_bg": (255, 243, 235, 255),
        "pill_border": (253, 205, 178, 255),
        "pill_dot": (226, 67, 41, 255),
        "pill_text": (194, 52, 28, 255),
        "subtitle": (226, 67, 41, 255),
        "row_bg": (255, 251, 248, 255),
        "row_border": (246, 222, 208, 255),
        "row_bar": (252, 109, 38, 255),
        "mr_badge_bg": (255, 238, 226, 255),
        "mr_badge_border": (252, 194, 162, 255),
        "mr_badge_text": (194, 52, 28, 255),
        "watermark": (226, 67, 41, 11),
        "divider": (244, 220, 206, 255),
    },
    "hrl-rose": {
        "name": "HRL Signature Rose-Crimson (Apple Light Mode)",
        "canvas_top": (253, 250, 251),
        "canvas_bottom": (255, 244, 247),
        "shadow_tint": (224, 83, 117, 28),
        "card_border": (246, 206, 217, 255),
        "stripe_top": (209, 0, 45),       # HRL Crimson #D1002D
        "stripe_bottom": (224, 83, 117),  # HRL Rose #E05375
        "pill_bg": (255, 240, 244, 255),
        "pill_border": (245, 198, 211, 255),
        "pill_dot": (224, 83, 117, 255),
        "pill_text": (190, 42, 80, 255),
        "subtitle": (224, 83, 117, 255),
        "row_bg": (255, 249, 251, 255),
        "row_border": (247, 218, 227, 255),
        "row_bar": (224, 83, 117, 255),
        "mr_badge_bg": (255, 236, 242, 255),
        "mr_badge_border": (244, 190, 205, 255),
        "mr_badge_text": (185, 28, 68, 255),
        "watermark": (224, 83, 117, 11),
        "divider": (246, 214, 224, 255),
    },
}

DEFAULT_SAMPLE_MRS = [
    {
        "ref": "gitlab-org/gitlab!264858",
        "repo": "gitlab-org/gitlab",
        "iid_str": "!264858",
        "title": "Add merge_request_iid parameter to save_pipeline MCP tool",
        "sha": "0a2b2f0e",
        "add": 417,
        "rem": 20,
        "files_count": 4,
        "primary_file": "app/services/mcp/tools/pipelines/save_pipeline_service.rb",
    },
    {
        "ref": "gitlab-org/modelops/applied-ml/code-suggestions/ai-assist!7642",
        "repo": "gitlab-org/ai-assist (Duo Workflow)",
        "iid_str": "!7642",
        "title": "fix(dws): read status_code directly from APIStatusError exceptions",
        "sha": "832277c2",
        "add": 12,
        "rem": 2,
        "files_count": 3,
        "primary_file": "duo_workflow_service/agent_platform/v1/components/agent_node.py",
    },
    {
        "ref": "gitlab-org/gitlab!264859",
        "repo": "gitlab-org/gitlab",
        "iid_str": "!264859",
        "title": "Add parent_iid filter to MCP list_work_items tool",
        "sha": "cdd86eb2",
        "add": 73,
        "rem": 3,
        "files_count": 7,
        "primary_file": "app/services/mcp/tools/work_items/list_work_items_service.rb",
    },
    {
        "ref": "gitlab-org/gitlab!261030",
        "repo": "gitlab-org/gitlab",
        "iid_str": "!261030",
        "title": "Extend Organizations::Organization#empty? to all attached resources",
        "sha": "2e255f6d",
        "add": 46,
        "rem": 1,
        "files_count": 2,
        "primary_file": "app/models/organizations/organization.rb",
    },
    {
        "ref": "gitlab-org/editor-extensions/gitlab-lsp!4407",
        "repo": "gitlab-org/gitlab-lsp",
        "iid_str": "!4407",
        "title": "feat(cli): show welcome card after /new in session with onboarding card",
        "sha": "fec1a3ca",
        "add": 61,
        "rem": 13,
        "files_count": 4,
        "primary_file": "packages/cli/app/src/commands/tui/welcome_prompts_controller.ts",
    },
]


def load_sf_font(size: int, weight: int = 400, mono: bool = False) -> ImageFont.FreeTypeFont:
    if mono:
        for p in ["/System/Library/Fonts/SFNSMono.ttf", "/System/Library/Fonts/Menlo.ttc"]:
            if os.path.exists(p):
                try:
                    return ImageFont.truetype(p, size)
                except Exception:
                    pass
    sf_path = "/System/Library/Fonts/SFNS.ttf"
    if os.path.exists(sf_path):
        try:
            f = ImageFont.truetype(sf_path, size)
            f.set_variation_by_axes([100, min(max(size, 17), 96), 400, weight])
            return f
        except Exception:
            pass
    fallback = "/System/Library/Fonts/Supplemental/Arial Bold.ttf" if weight >= 600 else "/System/Library/Fonts/Supplemental/Arial.ttf"
    if os.path.exists(fallback):
        return ImageFont.truetype(fallback, size)
    return ImageFont.load_default()


def draw_gitlab_tanuki_badge(draw: ImageDraw.ImageDraw, cx: int, cy: int, r: int) -> None:
    """Draws a crisp geometric GitLab Tanuki orange emblem centered at (cx, cy)."""
    # Left ear, right ear, and center face polygons in official GitLab Orange shades
    pts_left = [(cx - int(r * 0.75), cy - int(r * 0.85)), (cx - int(r * 0.95), cy + int(r * 0.05)), (cx, cy + int(r * 0.88)), (cx - int(r * 0.35), cy - int(r * 0.15))]
    pts_right = [(cx + int(r * 0.75), cy - int(r * 0.85)), (cx + int(r * 0.95), cy + int(r * 0.05)), (cx, cy + int(r * 0.88)), (cx + int(r * 0.35), cy - int(r * 0.15))]
    pts_center = [(cx - int(r * 0.38), cy - int(r * 0.15)), (cx + int(r * 0.38), cy - int(r * 0.15)), (cx, cy + int(r * 0.88))]
    pts_outer_l = [(cx - int(r * 0.95), cy + int(r * 0.05)), (cx - int(r * 1.12), cy + int(r * 0.32)), (cx, cy + int(r * 0.88))]
    pts_outer_r = [(cx + int(r * 0.95), cy + int(r * 0.05)), (cx + int(r * 1.12), cy + int(r * 0.32)), (cx, cy + int(r * 0.88))]

    draw.polygon(pts_outer_l, fill=(252, 163, 38, 255))  # #FCA326 Amber
    draw.polygon(pts_outer_r, fill=(252, 163, 38, 255))
    draw.polygon(pts_left, fill=(252, 109, 38, 255))     # #FC6D26 Tanuki Orange
    draw.polygon(pts_right, fill=(252, 109, 38, 255))
    draw.polygon(pts_center, fill=(226, 67, 41, 255))    # #E24329 Deep Flame Orange


def format_clean_meta(m: dict) -> str:
    repo = m.get("repo", "")
    if "ai-assist" in repo:
        repo = "gitlab-org/ai-assist"
    elif "gitlab-lsp" in repo:
        repo = "gitlab-org/gitlab-lsp"
    primary = m.get("primary_file", "")
    parts = [p for p in primary.split("/") if p]
    short_file = "/".join(parts[-2:]) if len(parts) >= 2 else primary
    extra = m.get("files_count", 1) - 1
    file_suffix = f" (+{extra} files)" if extra > 0 else ""
    return f"commit {m['sha']}   •   {repo}   •   {short_file}{file_suffix}"


def render_hrl_post_image(
    mrs_data: list = None,
    headline: str = "Upstream GitLab Merge Train — Ship Log",
    out_path: str = "hrl_gitlab_ship_log.png",
    theme_name: str = "gitlab-orange",
    category_label: str = "HRL TECHNOLOGY DIRECTORATE  •  GITLAB UPSTREAM ENGINEERING",
) -> str:
    mrs_data = mrs_data or DEFAULT_SAMPLE_MRS
    theme = THEMES.get(theme_name, THEMES["gitlab-orange"])

    # 2x Retina Supersampling for razor-sharp Apple typography & curves
    S = 2
    W, H = 1400 * S, 900 * S

    # 1. Warm Apple Alabaster-Apricot Studio Canvas
    canvas = Image.new("RGBA", (W, H), (*theme["canvas_top"], 255))
    c_draw = ImageDraw.Draw(canvas)
    r1, g1, b1 = theme["canvas_top"]
    r2, g2, b2 = theme["canvas_bottom"]
    for py in range(H):
        t = py / H
        r = int(r1 + (r2 - r1) * t)
        g = int(g1 + (g2 - g1) * t)
        b = int(b1 + (b2 - b1) * t)
        c_draw.line([(0, py), (W, py)], fill=(r, g, b, 255))

    # Fonts (Apple SF Pro & SF Mono at 2x Retina scale)
    f_pill = load_sf_font(13 * S, weight=700)
    f_h1 = load_sf_font(35 * S, weight=800)
    f_sub = load_sf_font(13 * S, weight=700)
    f_mr_title = load_sf_font(17 * S, weight=650)
    f_mr_meta = load_sf_font(13 * S, mono=True)
    f_mr_badge = load_sf_font(13 * S, weight=700)
    f_footer_bold = load_sf_font(14 * S, weight=700)
    f_footer_reg = load_sf_font(13 * S, weight=500)
    f_watermark = load_sf_font(124 * S, weight=900)

    # 2. Dual-Layer Apple Ambient Elevation Shadow
    card_box = [54 * S, 42 * S, W - 54 * S, H - 42 * S]
    shadow = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    s_draw = ImageDraw.Draw(shadow)
    s_draw.rounded_rectangle(
        [card_box[0] + 2 * S, card_box[1] + 14 * S, card_box[2] + 2 * S, card_box[3] + 18 * S],
        radius=28 * S,
        fill=theme["shadow_tint"],
    )
    s_draw.rounded_rectangle(
        [card_box[0], card_box[1] + 4 * S, card_box[2], card_box[3] + 6 * S],
        radius=28 * S,
        fill=(15, 23, 42, 10),
    )
    shadow = shadow.filter(ImageFilter.GaussianBlur(radius=20 * S))
    canvas = Image.alpha_composite(canvas, shadow)

    # 3. Main Pure White Card Shell + Vertical Gradient Left Accent Stripe
    card_layer = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    draw = ImageDraw.Draw(card_layer)
    draw.rounded_rectangle(card_box, radius=28 * S, fill=(255, 255, 255, 255), outline=theme["card_border"], width=2 * S)

    # Smooth vertical gradient stripe clipped to the card's left rounded geometry
    stripe_mask = Image.new("L", (W, H), 0)
    m_draw = ImageDraw.Draw(stripe_mask)
    m_draw.rounded_rectangle(card_box, radius=28 * S, fill=255)

    stripe_raw = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    st_draw = ImageDraw.Draw(stripe_raw)
    sr1, sg1, sb1 = theme["stripe_top"]
    sr2, sg2, sb2 = theme["stripe_bottom"]
    for py in range(card_box[1], card_box[3]):
        t = (py - card_box[1]) / max(1, (card_box[3] - card_box[1]))
        sc = (int(sr1 + (sr2 - sr1) * t), int(sg1 + (sg2 - sg1) * t), int(sb1 + (sb2 - sb1) * t), 255)
        st_draw.line([(card_box[0], py), (card_box[0] + 9 * S, py)], fill=sc)

    stripe_clipped = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    stripe_clipped.paste(stripe_raw, (0, 0), stripe_mask)
    card_layer = Image.alpha_composite(card_layer, stripe_clipped)
    draw = ImageDraw.Draw(card_layer)

    # 4. Subtle Typographic Watermark ("HRL") in bottom-right background above footer divider
    draw.text((W - 365 * S, H - 238 * S), "HRL", fill=theme["watermark"], font=f_watermark)

    # 5. Top Header: Category Pill with GitLab Tanuki Emblem + Official HRL Logo
    pill_box = [102 * S, 76 * S, 610 * S, 112 * S]
    draw.rounded_rectangle(pill_box, radius=18 * S, fill=theme["pill_bg"], outline=theme["pill_border"], width=1 * S)
    if theme_name == "gitlab-orange":
        draw_gitlab_tanuki_badge(draw, 124 * S, 94 * S, 9 * S)
        text_x = 142 * S
    else:
        draw.ellipse([118 * S, 90 * S, 126 * S, 98 * S], fill=theme["pill_dot"])
        text_x = 136 * S
    draw.text((text_x, 86 * S), category_label, fill=theme["pill_text"], font=f_pill)

    # Top-Right HRL Brand Logo
    for logo_path in [
        "/Users/pavankumars/Developer_Projects/omnitransform-ai-resources/hrl_logo_transparent.png",
        "/Users/pavankumars/Developer_Projects/omnitransform-ai-resources/hrl_brand_logo.png",
    ]:
        if os.path.exists(logo_path):
            try:
                logo = Image.open(logo_path).convert("RGBA")
                lw, lh = logo.size
                target_h = 38 * S
                target_w = int(lw * (target_h / lh))
                logo = logo.resize((target_w, target_h), Image.Resampling.LANCZOS)
                card_layer.paste(logo, (W - 102 * S - target_w, 75 * S), logo)
                break
            except Exception:
                pass

    # 6. Hero Title & Metrics Subtitle
    total_add = sum(m["add"] for m in mrs_data)
    total_rem = sum(m["rem"] for m in mrs_data)
    total_files = sum(m["files_count"] for m in mrs_data)
    draw.text((102 * S, 128 * S), headline, fill=(29, 29, 31, 255), font=f_h1)
    draw.text(
        (102 * S, 176 * S),
        f"GITLAB UPSTREAM MERGE TRAIN   •   {len(mrs_data)} MERGED MRS   •   {total_files} FILES ENGINEERED   •   +{total_add} / -{total_rem} LOC",
        fill=theme["subtitle"],
        font=f_sub,
    )

    # 7. Five Apple Bento-Style MR Rows (Inset Accent Bar, Clean Spacing, Zero Truncation)
    y = 212 * S
    for m in mrs_data:
        row_box = [102 * S, y, W - 98 * S, y + 92 * S]
        draw.rounded_rectangle(row_box, radius=16 * S, fill=theme["row_bg"], outline=theme["row_border"], width=1 * S)

        # Clean inset vertical accent bar (14px inside the card so it never touches the outer border)
        draw.rounded_rectangle(
            [116 * S, y + 16 * S, 121 * S, y + 76 * S],
            radius=2 * S,
            fill=theme["row_bar"],
        )

        # MR IID Pill Badge
        badge_box = [134 * S, y + 15 * S, 290 * S, y + 43 * S]
        draw.rounded_rectangle(badge_box, radius=14 * S, fill=theme["mr_badge_bg"], outline=theme["mr_badge_border"], width=1 * S)
        draw.ellipse([148 * S, y + 25 * S, 156 * S, y + 33 * S], fill=theme["pill_dot"])
        draw.text((164 * S, y + 21 * S), f"MERGED {m['iid_str']}", fill=theme["mr_badge_text"], font=f_mr_badge)

        # MR Title (Apple SF Pro Semibold #1D1D1F)
        title_str = m["title"] if len(m["title"]) <= 74 else m["title"][:71] + "..."
        draw.text((306 * S, y + 19 * S), title_str, fill=(29, 29, 31, 255), font=f_mr_title)

        # Diff Pill on Right
        diff_box = [W - 256 * S, y + 15 * S, W - 116 * S, y + 43 * S]
        draw.rounded_rectangle(diff_box, radius=14 * S, fill=(236, 253, 245, 255), outline=(167, 243, 208, 255), width=1 * S)
        draw.text((W - 240 * S, y + 21 * S), f"+{m['add']} / -{m['rem']} LOC", fill=(4, 120, 87, 255), font=f_mr_badge)

        # Clean Formatted Metadata Line (No ugly mid-path cutoff)
        meta_line = format_clean_meta(m)
        draw.text((134 * S, y + 56 * S), meta_line, fill=(100, 116, 139, 255), font=f_mr_meta)
        y += 104 * S

    # 8. Executive Footer (NO raw URLs — pure Apple/HRL executive attribution)
    footer_y = H - 104 * S
    draw.line([(102 * S, footer_y), (W - 98 * S, footer_y)], fill=theme["divider"], width=1 * S)

    # @hrl Tactile Pill
    hrl_pill = [102 * S, footer_y + 16 * S, 192 * S, footer_y + 48 * S]
    draw.rounded_rectangle(hrl_pill, radius=16 * S, fill=theme["pill_bg"], outline=theme["pill_border"], width=1 * S)
    draw.ellipse([118 * S, footer_y + 28 * S, 126 * S, footer_y + 36 * S], fill=theme["pill_dot"])
    draw.text((134 * S, footer_y + 23 * S), "@hrl", fill=(29, 29, 31, 255), font=f_footer_bold)

    draw.text(
        (210 * S, footer_y + 14 * S),
        "PAVAN KUMAR SADASHIV (HRL)   •   HRL INTERNATIONAL PRIVATE LIMITED",
        fill=(29, 29, 31, 255),
        font=f_footer_bold,
    )
    draw.text(
        (210 * S, footer_y + 35 * S),
        "Founder, Managing Director & Chief AI Systems Architect",
        fill=(100, 116, 139, 255),
        font=f_footer_reg,
    )

    # Right-Aligned Verified Pill Badge in Footer
    ver_pill = [W - 360 * S, footer_y + 16 * S, W - 98 * S, footer_y + 48 * S]
    draw.rounded_rectangle(ver_pill, radius=16 * S, fill=theme["pill_bg"], outline=theme["pill_border"], width=1 * S)
    draw.ellipse([W - 344 * S, footer_y + 28 * S, W - 336 * S, footer_y + 36 * S], fill=theme["pill_dot"])
    draw.text((W - 326 * S, footer_y + 24 * S), "VERIFIED UPSTREAM MERGE", fill=theme["pill_text"], font=f_mr_badge)

    # Downsample 2x -> 1x with LANCZOS for ultra-crisp anti-aliased finish
    composited = Image.alpha_composite(canvas, card_layer).convert("RGB")
    final_img = composited.resize((W // S, H // S), Image.Resampling.LANCZOS)
    os.makedirs(os.path.dirname(os.path.abspath(out_path)), exist_ok=True)
    final_img.save(out_path, "PNG", optimize=True)
    return out_path


def main() -> None:
    parser = argparse.ArgumentParser(description="Render HRL × LinkedIn Apple-Grade Light-Theme Post Image.")
    parser.add_argument("--theme", choices=["gitlab-orange", "hrl-rose"], default="gitlab-orange")
    parser.add_argument("--headline", default="Upstream GitLab Merge Train — Ship Log")
    parser.add_argument("--output", default="samples/hrl_gitlab_ship_log_apple_orange.png")
    parser.add_argument("--mrs-json", help="Optional path to JSON file containing MRs list.")
    args = parser.parse_args()

    mrs = None
    if args.mrs_json and os.path.exists(args.mrs_json):
        with open(args.mrs_json, "r", encoding="utf-8") as f:
            mrs = json.load(f)

    out = render_hrl_post_image(mrs_data=mrs, headline=args.headline, out_path=args.output, theme_name=args.theme)
    print(f"Rendered: {out}")


if __name__ == "__main__":
    main()

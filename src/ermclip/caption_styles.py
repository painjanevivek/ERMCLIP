"""Caption looks shared by the renderer, CLI and local style picker.

Fonts use installed desktop families. The references specify a look, not a
licensed font file. Forest Notes and Retro Serif name the two unlabelled looks.
"""
from dataclasses import asdict, dataclass
from typing import Literal


@dataclass(frozen=True)
class Style:
    name: str
    font: str = 'Arial'
    color: str = 'FFFFFF'
    outline_color: str = '101010'
    shadow_color: str = '101010'
    scale: float = 1
    bold: bool = True
    italic: bool = False
    outline: float = 2
    shadow: float = 0
    box: bool = False
    uppercase: bool = False
    spacing: float = 0
    max_words: int = 6
    glow: float = 0
    animation: bool = False
    multicolor: bool = False
    description: str = ''


STYLES = {
    'momentum': Style('Momentum', 'Arial Black', 'F47755', scale=1.65, italic=True, outline=2.5, max_words=1, animation=True, description='Orange italic word with a dark edge'),
    'click_bait': Style('Click Bait', 'Arial Narrow', '101010', 'DC82BF', scale=1.1, bold=False, outline=7, box=True, max_words=5, description='Black condensed text on a pink strip'),
    'highlighter': Style('Highlighter', 'Arial', '101010', 'DCFF43', outline=5, box=True, max_words=7, description='Bold black text on lime strips'),
    'studio_style': Style('Studio Style', 'Times New Roman', '101010', 'FFFFFF', scale=1.1, bold=False, outline=7, box=True, max_words=5, description='Black serif text on white'),
    'forest_notes': Style('Forest Notes', 'Georgia', 'ECEDE7', '354C40', bold=False, outline=7, box=True, max_words=7, description='Light serif text on a dark green box'),
    'retro_serif': Style('Retro Serif', 'Cooper Black', 'FFD581', shadow_color='F24939', scale=1.25, outline=0, shadow=3, max_words=4, description='Warm retro serif with a red offset shadow'),
    'bold_pop': Style('Bold Pop', 'Arial Black', '101010', 'FFFFFF', scale=1.55, outline=5, uppercase=True, max_words=1, animation=True, description='Heavy black word with a white edge'),
    'cherry_glow': Style('Cherry Glow', 'Arial Black', 'FF3629', 'FF3629', scale=1.15, outline=0, uppercase=True, max_words=5, glow=7, description='Red uppercase text with a soft red glow'),
    'pen_pal': Style('Pen Pal', 'Segoe Print', 'FFD858', shadow_color='101010', scale=1.25, bold=False, outline=0, shadow=2, max_words=4, description='Yellow handwritten text with a dark shadow'),
    'big_ideas': Style('Big Ideas', 'Arial', 'FFFFFF', bold=False, outline=1.5, max_words=5, description='White text with a fine black edge'),
    'blockout': Style('Blockout', 'Impact', '101010', 'CAC5BB', outline=3, box=True, uppercase=True, max_words=5, description='Black condensed capitals on a tight neutral box'),
    'editorial': Style('Editorial', 'Times New Roman', '101010', 'F4F7A4', scale=1.85, bold=False, outline=3, box=True, max_words=1, description='Large black serif word on a pale yellow marker'),
    'bold_lime': Style('Bold Lime', 'Impact', 'B7FF65', shadow_color='101010', scale=1.7, outline=0, shadow=5, uppercase=True, max_words=1, animation=True, description='Tall lime capitals with a black offset shadow'),
    'newsroom': Style('Newsroom', 'Arial Black', '101010', 'F3F2ED', outline=5, box=True, uppercase=True, max_words=5, description='Bold black capitals on an off-white box'),
    'solar_sign': Style('Solar Sign', 'Times New Roman', 'FFE66A', 'FFE66A', scale=1.2, outline=0, uppercase=True, max_words=5, glow=6, description='Gold serif capitals with a warm glow'),
    'refined': Style('Refined', 'Arial', 'F0CFB4', '606060', bold=False, outline=0.7, uppercase=True, max_words=5, description='Fine peach capitals with a grey edge'),
    'popcorn': Style('Popcorn', 'Arial', 'FFFFFF', scale=0.95, bold=False, outline=0, shadow=2, spacing=3, max_words=5, description='Small spaced white text with a dark shadow'),
    'eye_candy': Style('Eye Candy', 'Arial', 'FF5891', outline=1.2, shadow=1, max_words=5, multicolor=True, description='Pink, lilac and mint words with a dark edge'),
    'zine_scene': Style('Zine Scene', 'Arial Narrow', 'EEFF79', scale=1.2, bold=False, outline=2, max_words=5, description='Condensed yellow text with a black edge'),
    'digital_highlights': Style('Digital Highlights', 'Arial', 'FFFFFF', '303030', bold=False, outline=8, box=True, spacing=1, max_words=5, description='Light white text on a charcoal box'),
    'solid_stamp': Style('Solid Stamp', 'Arial', 'FFFFFF', shadow_color='A8A8A8', outline=0, shadow=2, max_words=5, description='White text with a pale embossed shadow'),
    'cinema_chic': Style('Cinema Chic', 'Times New Roman', 'E8B83C', scale=0.9, bold=False, outline=0.5, max_words=7, description='Small gold serif text'),
    'chunky_cartoon': Style('Chunky Cartoon', 'Arial Rounded MT Bold', 'FFE59A', 'D2AF67', outline=1.2, max_words=5, description='Rounded yellow letters with a warm edge'),
    'front_page': Style('Front Page', 'Impact', 'FFFFFF', shadow_color='A0A0A0', outline=0, shadow=2, uppercase=True, spacing=1, max_words=5, description='White condensed capitals with an offset shadow'),
    'short_yellow': Style('Podcast Yellow', 'Arial', 'FFDF35', outline=2, shadow=1, uppercase=True, max_words=3, description='Short yellow speech captions based on the supplied podcast reference'),
}
PRESET_IDS = ('highlight', 'plain', 'pop', *STYLES)
CaptionPreset = Literal[PRESET_IDS]


def catalog():
    return [{'id': key, **asdict(style)} for key, style in STYLES.items()]

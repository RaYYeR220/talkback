"""Sensitive topics a producer must see before a line airs.

Matching uses the lexicon's normalisation (accents, Arabic variants, word
boundaries), so lists only need one spelling per form.
"""

from __future__ import annotations

from talkback.clearance.lexicon import base_lang, match_terms

TOPICS: dict[str, dict[str, list[str]]] = {
    "injury": {
        "en": ["injury", "injured", "injuries", "limping", "limps off", "limped off",
               "stretcher", "stretchered off", "concussion", "hamstring", "ligament", "fracture",
               "physio", "medical staff", "receiving treatment", "pulled up"],
        "es": ["lesión", "lesiones", "lesionado", "lesionada", "se retira lesionado", "camilla",
               "conmoción", "isquiotibiales", "ligamento", "fractura", "molestias",
               "asistencia médica", "fisioterapeuta", "cojeando"],
        "ar": ["إصابة", "إصابات", "مصاب", "مصابا", "يعرج", "نقالة", "ارتجاج", "العضلة الخلفية",
               "الرباط الصليبي", "تعرض لكسر", "الجهاز الطبي", "يتلقى العلاج"],
        "pt": ["lesão", "lesões", "lesionado", "contusão", "machucado", "maca", "concussão",
               "posterior da coxa", "ligamento", "fratura", "dores", "atendimento médico",
               "departamento médico", "mancando"],
    },
    "discipline": {
        "en": ["yellow card", "red card", "booked", "booking", "sent off", "sending off",
               "dismissed", "dismissal", "second yellow", "straight red", "suspension",
               "suspended", "banned", "cautioned", "violent conduct"],
        "es": ["tarjeta amarilla", "tarjeta roja", "amonestado", "amonestación", "expulsado",
               "expulsión", "segunda amarilla", "roja directa", "sanción", "sancionado",
               "suspendido"],
        "ar": ["بطاقة صفراء", "البطاقة الصفراء", "بطاقة حمراء", "البطاقة الحمراء", "إنذار",
               "الإنذار الثاني", "طرد", "مطرود", "إيقاف", "موقوف", "عقوبة"],
        "pt": ["cartão amarelo", "cartão vermelho", "amarelado", "advertido", "expulso",
               "expulsão", "segundo amarelo", "vermelho direto", "suspenso", "suspensão",
               "punição"],
    },
    "referee": {
        "en": ["referee", "ref", "VAR", "linesman", "linesmen", "assistant referee",
               "fourth official", "officials", "officiating", "disallowed", "overturned",
               "handball", "penalty decision", "offside call", "controversial decision"],
        "es": ["árbitro", "arbitraje", "VAR", "juez de línea", "linier", "cuarto árbitro",
               "anulado", "anula el gol", "revisión", "decisión polémica", "polémica arbitral"],
        "ar": ["الحكم", "حكم المباراة", "حكم اللقاء", "حكم الراية", "الحكم المساعد",
               "الحكم الرابع", "تقنية الفيديو", "الفار", "VAR", "ألغى", "إلغاء الهدف", "قرار مثير للجدل", "لمسة يد"],
        "pt": ["árbitro", "arbitragem", "VAR", "bandeirinha", "quarto árbitro", "anulado",
               "anulou o gol", "revisão", "lance polêmico", "decisão polêmica", "mão na bola"],
    },
    "personal": {
        "en": ["family", "wife", "girlfriend", "bereavement", "funeral", "passed away", "died",
               "divorce", "pregnant", "personal reasons", "personal matter", "mental health",
               "illness", "private life"],
        "es": ["familia", "esposa", "novia", "luto", "funeral", "falleció", "fallecimiento",
               "divorcio", "embarazada", "motivos personales", "asuntos personales",
               "salud mental", "enfermedad", "vida privada"],
        "ar": ["عائلة", "عائلته", "زوجته", "حداد", "جنازة", "وفاة", "توفي", "طلاق",
               "ظروف شخصية", "أسباب شخصية", "الصحة النفسية", "مرض", "حياته الخاصة"],
        "pt": ["família", "esposa", "namorada", "luto", "funeral", "faleceu", "falecimento",
               "divórcio", "grávida", "motivos pessoais", "questões pessoais", "saúde mental",
               "doença", "vida pessoal"],
    },
}

LANGS = frozenset.intersection(*(frozenset(by_lang) for by_lang in TOPICS.values()))


def sensitive_topics(text: str, lang: str) -> set[str]:
    base = base_lang(lang)
    if base not in LANGS:
        raise ValueError(f"no sensitive-topic lists for language {lang!r}")
    return {topic for topic, by_lang in TOPICS.items() if match_terms(text, by_lang[base], lang)}

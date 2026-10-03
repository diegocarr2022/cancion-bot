"""Red de seguridad de idioma para la letra de las canciones EN (US y Etsy).

El prompt del chat EN ya le exige al modelo escribir TODA la letra en ingles (los nombres propios en espanol se
conservan), pero a veces se desliza al espanol (p. ej. estilos latinos o nombres en espanol). Un prompt no es una
garantia: aca se revisa la letra antes de gastar un credito / generar la cancion y, si esta en espanol, se le
devuelve al modelo la instruccion de reescribirla en ingles y volver a pedir aprobacion.

Heuristica deliberadamente simple (sin dependencias ni llamadas extra): cuenta palabras funcionales que son
casi exclusivamente espanolas contra palabras funcionales inglesas. Una letra en ingles con algun verso o apodo en
espanol ("mi amor", "Ana, mi vida") NO se marca; una letra mayormente en espanol si.
"""
import re

_ES = frozenset(
    "de que el en y los las del por para con una su lo como más mas pero se es está esta están qué te tu nos sus ya muy "
    "sin sobre cuando donde dónde porque siempre nunca yo eres soy estoy mi mis al un unos unas hay fue ser son "
    "tengo tiene quiero puedo todo todos nada algo aquí aquí ahí aun aún también tan cada entre hasta desde "
    "cuando mientras aunque si sí así".split()
)
_EN = frozenset(
    "the and you your i my we our to of in is it that for with on are was be this but all me so when like can will "
    "just every from they her his she he what who how why there here have has had do does did not no yes if or at by as "
    "an a them us been were would could should still never always".split()
)
_WORD = re.compile(r"[a-záéíóúñü']+", re.I)


def spanish_score(text: str) -> tuple[int, int]:
    """(palabras funcionales en espanol, palabras funcionales en ingles) - ignora las etiquetas [Verse 1] etc."""
    cleaned = re.sub(r"\[[^\]]*\]", " ", text or "")
    words = [w.lower() for w in _WORD.findall(cleaned)]
    es = sum(1 for w in words if w in _ES and w not in _EN)
    en = sum(1 for w in words if w in _EN and w not in _ES)
    return es, en


def looks_spanish(text: str) -> bool:
    es, en = spanish_score(text)
    return es >= 6 and es > en

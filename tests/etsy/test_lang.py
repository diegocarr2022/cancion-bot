import sys; sys.path.insert(0, ".")
from app.lang_guard import looks_spanish, spanish_score
cases = {
"ES full": ("[Verse 1]\nDiez años de viajes y café al amanecer\nCantando desafinados nuestra canción favorita\nTú convertiste cada kilómetro en hogar\n[Chorus]\nDiez años y te elegiría otra vez\nPor cada amanecer, por cada curva del camino\nAna, eres mi canción favorita", True),
"ES reggaeton": ("[Verse 1]\nMami tú eres la que yo quiero, no puedo parar\nEn la noche con tu cuerpo me quiero perder\nSi tú me miras así, ya no sé qué hacer\n[Chorus]\nBaila conmigo toda la noche, que la vida es una sola\nPorque contigo todo es mejor, y no hay nadie más", True),
"EN plain": ("[Verse 1]\nTen years of road trips and coffee at dawn,\nSinging off-key to our favorite song,\nYou turned every mile into home\n[Chorus]\nTen years, and I'd choose you again,\nThrough every sunrise, every bend,\nAna, you're my favorite song", False),
"EN with names+mi amor": ("[Verse 1]\nMijo, you grew up so fast, mi amor,\nAbuela Carmen taught you how to dance in the kitchen,\nAnd I still hear her laughing, la la la\n[Chorus]\nWe love you, Nena, mi vida, with all that we are,\nYou are the light of every room, and the heart of our home", False),
"EN latin flavor": ("[Verse 1]\nBaila, baila with me tonight under the stars,\nYour smile is the only fire that I need,\nDale, mami, take my hand and never let it go\n[Chorus]\nWe dance all night, you and me, perreo in the moonlight,\nThis is our song, and nobody can take it away", False),
"mixed half": ("[Verse 1]\nYou are my everything, mi corazón, te quiero tanto\nSiempre estaré contigo, you know that it's true\n[Chorus]\nPorque tú eres mi vida, y yo soy tuyo para siempre\nI will love you till the end, y nada nos separa", None),
}
bad = 0
for name, (t, exp) in cases.items():
    r = looks_spanish(t); print(("PASS" if exp is None or r == exp else "FAIL"), name, spanish_score(t), "->", r)
    bad += 0 if exp is None or r == exp else 1
sys.exit(bad)

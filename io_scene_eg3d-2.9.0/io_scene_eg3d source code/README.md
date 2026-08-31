# 300 Heroes Importer für Blender 4.2+ — `.model` und `.x`

Importiert beide Modellformate des Spiels 300英雄 / 300 Heroes direkt in
Blender: Mesh, UV, Skelett, Skin-Weights und Animationen, mit sehr
ausführlicher Diagnose.

| Format | Engine | Erkennung |
|---|---|---|
| `.model` | neuer (`EG3D` / `ezgame`) | Magic `EG3D` |
| `.x` | älter (`JUMPX V5.01`) | Magic `JUMPX` |

Das Format wird an der Signatur erkannt, nicht an der Endung. **Achtung:** die
`.x`-Dateien sind trotz Endung *keine* DirectX-X-Files.

---

## Installation

**Blender 4.2 – 5.x**

1. `io_scene_eg3d-1.0.0.zip` herunterladen (nicht entpacken!)
2. Blender öffnen → `Edit > Preferences > Get Extensions`
3. Oben rechts auf den Pfeil ▾ → `Install from Disk...`
4. Die `.zip` auswählen

Das Addon aktiviert sich selbst. Danach:

> **File > Import > 300 Heroes EG3D Model (.model)**

Falls Blender die Datei als „Legacy Add-on" behandeln soll, funktioniert auch
`Preferences > Add-ons > Install from Disk` — beides geht, das Paket enthält
sowohl `blender_manifest.toml` als auch `bl_info`.

**Mehrfachauswahl:** im Dateibrowser können mehrere `.model` auf einmal
markiert werden, sie werden nacheinander importiert.

---

## Die Import-Optionen

Im Dateibrowser rechts, aufgeteilt in vier Panels.

### Transform

| Option | Default | Bedeutung |
|---|---|---|
| **Scale** | 1.0 | Gleichmäßige Skalierung |
| **Orientation** | Z up (as stored) | Diese Modelle sind bereits Z-up. `Y up → Z up` nur nutzen, wenn das Modell auf dem Gesicht liegt |
| **Handedness** | **Automatic** | Wird pro Datei gemessen, siehe unten. Manuell überschreibbar |
| **Character faces** | **−Y** | Welche Weltachse die Figur nach dem Import anschaut. −Y ist Blenders Konvention (Numpad 1 zeigt das Gesicht). Andere Werte hängen nur eine Z-Drehung an |
| **Flip UV V** | **an** | Die Dateien speichern V nach unten (DirectX), Blenders V zeigt nach oben. Gegen die echten Texturen von `336_skin1.model` verifiziert. Nur ausschalten, wenn eine Textur kopfsteht |

### Include

| Option | Default | Bedeutung |
|---|---|---|
| **Armature** | an | Skelett aus den Inverse-Bind-Matrizen |
| **Skin weights** | an | Vertexgruppen + Armature-Modifier |
| **Only skeleton bones** | **an** | Nur Bones, die in einer Bone-Palette vorkommen, plus deren Vorfahren. Aus = auch Effekt-Attachment-Points und Mesh-Instanzen, die eine andere Achsenkonvention haben und seitlich aus dem Modell herausstehen |
| **Vertex colours** | an | Attribut 3 (RGBA u8), falls vorhanden |
| **Animations** | **an** | Alle Clips als Actions, siehe unten |
| **Assign first action** | **an** | Wendet den ersten Clip direkt an. Aus = Bind-Pose, dann liegen aber Waffen und andere Requisiten am Ursprung (siehe unten) |
| **Align clips to rest pose** | **an** | Dreht den Clip-Raum +90° um X, damit der animierte Charakter aufrecht steht |
| FPS / Max frames | 30 / 600 | Sampling der Clips |

### Geometry

| Option | Default | Bedeutung |
|---|---|---|
| **Normals** | From geometry | Empfohlen. Siehe „Attribut 1" unten |
| **Skip `_c` billboards** | aus | Materialien mit Suffix `_c` sind Camera-Facing-Cards. Ihre gespeicherte Geometrie ist nur ein Template, das die Engine jeden Frame zur Kamera dreht — im Viewport sieht das beliebig aus. Anschalten, wenn sie stören |
| **Merge by distance** | **0 = aus** | ⚠️ Bitte aus lassen. Siehe unten |
| Default bone length | **0 = automatisch** | Länge für Bones ohne Kind. Automatisch sind es 2 % der Modellgröße — ein fester Wert ist für eines der beiden Formate falsch, ihre Maßstäbe unterscheiden sich um Faktor 40 |

### Debug

| Option | Default | Bedeutung |
|---|---|---|
| **Log level** | INFO | ERROR / WARN / INFO / DEBUG / TRACE. `DEBUG` zeigt jeden Attribut-Offset, `TRACE` zusätzlich Quantisierungskonstanten und Bone-Listen |
| **Mesh diagnostics** | an | Der Topologie-Report (siehe unten). Läuft für **beide** Formate |
| **Boundary loop report** | aus | Listet jede Randschleife mit Größe — trennt echte Löcher von offenen Shell-Rändern |
| **Keep raw attribute 1** | aus | Legt das undekodierte Attribut 1 als Farb-Layer ab (Forschung) |
| **Write .log next to file** | an | `<modelname>_eg3d_import.log` |
| **Write log into .blend** | an | Text-Datablock, lesbar im Scripting-Workspace |
| **Dump JSON metadata** | aus | Die rohen Metadaten als Text-Datablock |

---

## Standalone ohne Blender

`eg3d_parse.py` hat keine `bpy`-Abhängigkeit:

```bash
python eg3d_parse.py 157_skin11.model
python eg3d_parse.py 157_skin11.model --verbose
```

Gibt Container-Header, Materialien, Texturen, Buffer-Layout-Tabelle und den
kompletten Mesh-Diagnose-Report aus. Praktisch zum schnellen Prüfen neuer
Charaktermodelle, ohne Blender zu starten.

---

## Der Diagnose-Report — wie man ihn liest

Genau dieser Report beantwortet die Frage „warum habe ich Löcher".

### 1. Buffer-Layout-Tabelle

```
block                                   start        end      gap
g0_s0.POSITION                        2711864    2792800        0
g0_s0.ATTR1(packed)                   2792800    2846740        0
g0_s0.UV0                             2846740    2900696        0
...
gaps: 31 blocks, 1 non-zero, max=2701676
```

**Jeder `gap` muss 0 sein.** Wenn alle Gaps denselben Wert ≠ 0 haben, ist die
Basis-Adresse falsch — der Importer schreibt dann selbst
`EVERY gap is N bytes -> your buffer base is off by N!` ins Log.

### 2. Pro Submesh

```
  raw topology     : edges 28092  boundary 10224  non-manifold 0
  welded topology  : verts 8034   boundary 378    non-manifold 8
  -> 9846 of 10224 'boundary' edges disappear after welding:
     those are UV/hard-edge splits, NOT holes.
  winding consistent: 100.0% of 17868 interior edges
  signed volume     : -0.06504  (faces point INWARD -> flip winding)
  edge length       : p50=0.0139 p99=0.1018 max=0.2570  (>20% diag: 0)
  weight sums       : min=0.9992 med=1.0000 max=1.0000  bad=0
  bone indices      : max=94, palette size=95  [OK]
```

Interpretationshilfe:

| Beobachtung | Bedeutung |
|---|---|
| `INDICES OUT OF RANGE` | Falsche Buffer-Basis oder falsche Index-Breite |
| viele `boundary raw`, fast keine `boundary welded` | **Kein Loch.** Split-Vertices an UV-/Hard-Edge-Nähten. Normal für Game-Assets |
| `boundary welded` bleibt hoch | Offene Shell (Umhang, Bänder, Alpha-Cards) oder echtes Loch |
| `bone axis alignment` > 1,0 | unmöglich für ein Skalarprodukt normierter Vektoren. Bind-Matrizen können Skalierung enthalten, die Achsen müssen vor dem Vergleich normiert werden |
| `winding consistent` < 100 % | Index-Buffer falsch interpretiert. Gemessen wird nur über **Innenkanten**, also Kanten mit genau zwei Faces — jede andere Zählweise bestraft offene Geometrie: ein perfektes Zwei-Dreieck-Kärtchen käme sonst auf 33,3 %, weil vier seiner sechs gerichteten Kanten am Rand liegen. Alle vier Testdateien liegen bei **100 %** |
| `signed volume` negativ | Linkshändige Quelle → Winding flippen |
| Kanten > 20 % Diagonale | Die klassischen „Bridge-Triangles" |
| `weight sums` ≠ 1 | Weight-Buffer verschoben |
| `bone indices ... OUT OF RANGE` | Indices werden global statt palette-lokal gelesen |

**Wichtig:** Die Kantenlängen werden immer gegen die Diagonale des
**gesamten Modells** gemessen, nie gegen die eines einzelnen Submeshes. Ein
kleines Submesh hat eine kleine Diagonale, dann werden seine völlig normalen
Dreiecke als „Riesen" markiert.

### 3. Boundary-Loop-Report (optional)

```
loop  351 verts  extent  12.4% of diag  centre [...]  open border (do NOT fan-fill)
loop   23 verts  extent   1.1% of diag  centre [...]  COMPACT (real hole candidate)
```

Eine Schleife, deren Bounding-Box ein großer Anteil des Modells ist, ist kein
Loch, sondern der offene Rand einer Shell. Solche Schleifen mit einem
Centroid-Fan zu füllen erzeugt riesige Flächen quer durchs Modell — schlimmer
als gar nicht füllen.

---

## Bekannte Eigenheiten

### Handedness: warum das automatisch gemessen wird

Beide Formate sind linkshändig, brauchen für Blender also genau **eine**
Orientierungsumkehr — entweder Winding umdrehen oder eine Achse negieren.
Welche der beiden richtig ist, unterscheidet sich aber **zwischen den
Formaten**. Deshalb sind zwei unabhängige Messungen nötig:

1. **Vorzeichen des Volumens** — negativ heißt, die Flächen zeigen aktuell
   nach innen, es ist also überhaupt eine Umkehr nötig.
2. **L/R-Bone-Positionen** — eine Figur, die nach −Y blickt, muss ihre
   `... L ...`-Bones auf der **+X**-Seite haben. Liegen sie bei −X, ist die
   Geometrie selbst gespiegelt und nur das Negieren von X bringt links und
   rechts dorthin zurück, wo ihre Namen es behaupten.

Gemessen:

| Datei | L/R-Paare, mittleres X | Volumen | Ergebnis |
|---|---|---|---|
| `157_skin11.model` | links −0.441, rechts +0.441 | −0.1 | **Mirror X** |
| `334.model` | links −0.463, rechts +0.462 | −0.2 | **Mirror X** |
| `020_skin2.x` | links **+22.21**, rechts −22.21 | −35944 | **nur Winding** |

Die `.x`-Dateien sind also **nicht** gespiegelt, die `.model`-Dateien schon.
Wer bei `.x` trotzdem `Mirror X` erzwingt, vertauscht links und rechts —
der linke Arm bewegt dann den rechten. Deshalb ist `Automatic` der Standard.

Wichtig für die Implementierung: gespiegelt wird per **Konjugation**
(`Mir @ B @ Mir`), nicht per Linksmultiplikation. Nur so bleibt die
Determinante bei +1, die Bone-Matrix also eine echte Rotation. Bei
Linksmultiplikation wird sie −1, und `to_quaternion()` liefert Müll. Für
Animationen kürzt sich die Konjugation bei allen Kind-Bones weg
(`(Mir A Mir)⁻¹ (Mir B Mir) = Mir (A⁻¹B) Mir`), sie muss also nur auf
Wurzel-Bones und die Ruhepose angewendet werden.

### „Die Polygone sehen kaputt aus"

Wenn flache graue Keile mit einer Kugel am Ende aus Armen, Beinen und Fingern
ragen: das sind **keine Polygone**, das ist die Armature. Blenders
Oktaeder-Darstellung sieht von der Seite wie ein Keil aus, und lange Bones
stechen durch dünne Gliedmaßen hindurch.

Gegenprobe in zwei Sekunden: im Outliner das Auge neben der Armature
zuklappen. Verschwinden die Keile, war es die Armature.

Der Importer stellt die Armature deshalb auf **Stick**-Darstellung und
**In Front aus**. Wer die Oktaeder zurück will: Armature auswählen →
Object Data Properties → Viewport Display → Display As.

### Merge by Distance bitte aus lassen

Das Format speichert Vertices an harten Kanten und UV-Nähten doppelt. Bei
`157_skin11` Submesh 0: 13485 Vertices, nach Verschweißen 8034. **Diese
Duplikate sind die harten Kanten.** Verschweißt man sie, wird das Modell
überall weich und die UVs reißen. Deshalb Default 0.

Genau deshalb ist auch `Normals: From geometry` die richtige Wahl: weil die
Vertices an harten Kanten getrennt sind, erzeugt normales Smooth-Shading die
Original-Kantenhärte von selbst.

### Vollständigkeitsprüfung

Beide Formate wurden Byte für Byte auditiert.

**`.model`:** vom Binärblock sind **99,95 %** durch bekannte Strukturen erklärt
(157_skin11: 1796 von 3454668 Byte offen, 334: 2818 von 1965528). Die Lücken
sind ausschließlich 2-Byte-Ausrichtungspadding zwischen Puffern, die größte
zusammenhängende Lücke ist 2 Byte. Alle acht JSON-Sektionen werden gelesen.

**`.x`:** Block 2 geht restlos auf (Materialien + Geo-Structs + Meshdaten +
Bones = exakt die Blockgröße). Block 1 ist vollständig in Sektionen zerlegt:
Header, Texturen, Materialien, Geometrie, 93 Bone-Deskriptoren à 172 Byte plus
1548 Byte Namenstabelle, die `bgp`-Sektion und 21 Actions à 90 Byte.

Zwei Sektionen enthalten **reservierten, aber ungenutzten Platz**: die
Material-Structs (`715 × 4 float` pro Material) und die Geo-Structs
(`715 × 1 float` pro Mesh) sind in dieser Datei komplett null. Das sind
vorgesehene Kanäle für pro Frame animierte Material- und Mesh-Werte, die dieses
Modell nicht benutzt.

Die `bgp`-Sektion ist eine **deduplizierte Bone-Paletten-Tabelle**: 504
Einträge à 12 Byte, jeder zeigt auf eine Liste von `uint32`-Bone-Indices.
Eintrag 0 lautet `[50, 26, 51, 0]` — identisch mit den inline im Skin-Record
von Vertex 0 stehenden Indices. Sie ist für den Import also redundant, die
Engine nutzt sie vermutlich zum Batching von Draw-Calls.

### Was wirklich unbekannt bleibt

Nur noch die `.model`-Seite, beide für den Import entbehrlich. Mit
`Keep undecoded attributes` landen sie als Farb-Layer im Mesh.

**`.model`, Attribut 1** (4 Byte/Vertex): es sind **2 × uint16**, bewiesen über
die Byte-Glätte — Byte 1 und 3 (die High-Bytes) sind über Kanten glatt
(Faktor 3,3 bzw. 3,1), Byte 0 und 2 sind Rauschen (1,1). Als `uint16`
normalisiert liegt der Wert in 0..1. Getestet und **verworfen**: int8-Normale,
uint8, 10:10:10:2, 11:11:10, oktaedrisch in allen 96 Vorzeichen- und
Achsenvarianten, sphärisch, Hemisphere, TBN-Quaternion (QTangent) in beiden
Komponentenordnungen und allen drei Achsen. Bestes Ergebnis gegen robuste
geometrische Normalen: |dot| = 0,74 statt 1,0. Es korreliert also schwach mit
der Oberfläche, dekodiert aber mit keiner Standardkodierung.

**Gelöst:** das eine Byte pro Vertex im `.x` ist der **Index in die
`bgp`-Palettentabelle**. Geprüft an **allen 20.514 Vertices** von
`045_skin5_huicheng.x`: `bgp[byte]` ist exakt die Bone-Liste, die im
Skin-Record desselben Vertex steht — 100,0000 %, und die benutzten Indices
decken lückenlos 0..186 bei `nbgp = 187` ab. Über alle vier Testdateien
stimmen 100 % der Vertices mit `byte < 255`.

Das Byte ist ein `uint8` und **sättigt bei 255**. Dateien mit mehr als 255
Paletten — `156_skin10.x` hat 312, `045.x` 411, `020_skin2.x` 504 — können die
höheren Indices nicht ausdrücken, dort steht bei allen betroffenen Vertices
255. Das erklärt auch die frühere Fehldeutung: bei `020_skin2.x` sind zwei
Meshes komplett 255, was wie „Maximalwert einer Maske" aussah.

Für den Import ist es **redundant**, weil die Bone-Indices ohnehin im
Skin-Record stehen. Mit `Keep undecoded attributes` landet es als Farb-Layer
`JUMPX_palette_index` im Mesh, um die Draw-Batches sichtbar zu machen, in die
die Engine das Mesh zerlegt.

### Attribut 1: gelöste Normalen-Kodierung

Attribut 1 im `.model` ist eine **Normale als Höhe plus Azimut**, kein Vektor:

```
int16 c0 -> z    = c0 / 16384        (15 Bit, Bereich -1..1)
int16 c1 -> phi  = c1 / 32768 * pi   (16 Bit, voller Kreis)
r = sqrt(1 - z*z)
n = (-r*sin(phi), -z, -r*cos(phi))
```

Der Weg dahin: Byte 1 und 3 sind über Mesh-Kanten glatt, Byte 0 und 2 sind
Rauschen — die Signatur zweier 16-Bit-Werte in Little-Endian. Byte 1 nimmt dann
nur 128 der 256 Werte an, und zwar genau die Muster `00xxxxxx` und `11xxxxxx`:
Bit 7 ist immer gleich Bit 6, also ein vorzeichenerweiterter **15-Bit**-Wert.
Dass eine Komponente 15 Bit braucht und die andere 16, schließt eine
oktaedrische Kodierung aus — dort hätten beide denselben Bereich — und zeigt
auf Winkel plus Höhe.

Verifikation gegen flächengewichtete geometrische Normalen:

| | 157_skin11 | 334 |
|---|---|---|
| gekrümmte Submeshes | +0,970 / +0,967 / +0,973 | +0,990 / +0,986 / +0,969 / +0,973 |
| flache Card-Submeshes | **+1,000** | **+1,000** |

Bei den flachen Submeshes ist die Referenznormale exakt, und dort stimmt die
Dekodierung auf drei Nachkommastellen. Die Vektoren haben Einheitslänge auf
fünf Stellen und stehen mit |dot| 0,004 bis 0,15 senkrecht auf der
gespeicherten Tangente — wie es ein TBN-System verlangt.

Damit steht im Import unter **Normals** die Option `From the file` zur
Verfügung. Die frühere Einschätzung, das Attribut dekodiere nicht als
Einheitsnormale, war falsch: getestet wurden int8, uint8, 10:10:10:2,
11:11:10, oktaedrisch in allen Vorzeichen- und Achsenvarianten und QTangent —
alle scheiterten, weil keine davon zwei Komponenten mit *unterschiedlicher*
Auflösung vorsieht.

### Alter Stand: Attribut 1 sind keine Normalen

4 Bytes pro Vertex, wird gern als `int8 xyz / 127` gelesen. Gemessen:

* mittlere Länge 0.80 statt 1.0 (Quantisierung auf 1/127 kann das nicht)
* Übereinstimmung mit der Flächennormale zufällig (|dot| ≈ 0.35)
* eine Brute-Force-Suche über die **ganze** Datei findet keinen i8×4-Block,
  der zur Geometrie passt

Attribut **2** dagegen ist ein echter Tangent: Einheitslänge exakt 1.000 und
senkrecht zur Fläche (|dot| ≈ 0.10). Attribut 1 ist also irgendetwas anderes
(gepackt, evtl. Farbe/Shader-Daten). Bei 100 % konsistentem Winding sind
berechnete Normalen völlig ausreichend — deshalb der Default.

Wer weiterforschen will: `Keep raw attribute 1` legt die rohen Bytes als
Farb-Layer ab.

### „Die Waffen fehlen"

Requisiten sind eigene Submeshes an eigenen Bones und liegen in der Bind-Pose
**am Ursprung**, nicht in der Hand. Erst die Animation setzt sie an ihren
Platz. Gemessen an `336_skin1.model`:

| | Bind-Pose | mit `bat_idle` |
|---|---|---|
| Körper `g0_s0` | z 0.00 … 2.08 | z −0.94 … 0.32 |
| Waffen `g1_s0` | z −0.28 … 0.28 | z −0.22 … 0.10 |

In der Bind-Pose liegen die Schwerter also flach am Boden unter der Figur, mit
Animation sitzen sie im selben Bereich wie der Körper. Deshalb sind
**Animations** und **Assign first action** seit 1.16.0 standardmäßig **an**.

### „Nach dem Import ist die Bind-Pose weg" und „ich sehe keine Keyframes"

Beides ist Blender-Bedienung, kein Importfehler.

**Bind-Pose:** sobald eine Action an der Armature hängt, zeigt Blender die
**Pose** statt der Ruhelage. Umschalten unter *Object Data Properties →
Skeleton → Pose Position / Rest Position*. Seit 1.5.0 weist der Importer
standardmäßig **keine** Action mehr zu, das Modell bleibt also in der
Bind-Pose; die Clips liegen alle im Action Editor bereit.

**Keyframes:** die liegen auf den **Pose-Bones**, nicht am Objekt. Der Dope
Sheet filtert per Default auf *Only Show Selected* (Mauszeiger-Symbol im
Header). Im Object Mode ist kein Bone selektiert, also bleibt die Liste leer.
Entweder den Filter ausschalten oder in den Pose Mode wechseln und `A`
drücken.

### Animationen: Rest-Pose ≠ Frame 0

`meta[5]` enthält **nicht** die Bind-Pose, sondern Frame 0 des `autoPlay`-Clips
(byte-identisch geprüft). Die echte Bind-Pose steckt nur in den
Inverse-Bind-Matrizen. Zusätzlich animiert die Engine in einem **Y-up**-Weltraum,
während das Mesh **Z-up** modelliert ist. Gemessen an beiden Referenzmodellen:
Pelvis liegt im Bind-Raum bei (0, 0, ~1.0) und im Node-Raum bei (0, ~1.0, 0).

`Align clips to rest pose` korrigiert das mit einer festen +90°-Drehung um X.
Die Drehung muss nur auf **Wurzel-Bones** angewendet werden — bei jedem Kind
steht sie auf beiden Seiten von `animWorld(parent)⁻¹ @ animWorld(child)` und
kürzt sich weg.

Was danach übrig bleibt, ist **kein Fehler**: die Bind-Pose und die
Engine-Posen sind schlicht verschiedene Posen. Gemessene Restabweichung bei
Frame 0 des Idle-Clips: ~4 % der Modellgröße (157_skin11), ~7 % (334). Beim
Umschalten von Rest- auf Pose-Modus ruckt der Charakter also minimal — genau
so verhält sich das Original auch.

Zeitrahmen: alle 17 Clips von `157_skin11` brauchen zusammen etwa 6 Sekunden.

### Texturen

`.dds` liegen **nicht** in der `.model`. Der Importer sucht neben der Datei
und in `textures/`, `texture/`, `tex/` sowie eine Ebene höher, nach dem
Dateinamen aus den Metadaten mit den Endungen `.dds .png .tga .tif .jpg .bmp`.
Wird nichts gefunden, steht `texture ... NOT FOUND` im Log und das Material
bleibt ohne Bild. Die Originale liegen im Spiel unter `data/character/`.

---

## Das `.x`-Format (JUMPX V5.01)

```
0x00  "JUMPX V5.01" + Werbe-Strings
0x50  u32 = 8, u32 = 300 (Groesse der TOC)
0x58  TOC: [4-Byte-Tag][u32 groesse=4][u32 wert]
      n<x> = Anzahl, a<x> = START-Offset in Block 1
      Tags: tex mtl geo bon bgp att rib prt act ...
....  u32 x4 = roh1, roh2, gepackt1, gepackt2
      zlib-Stream 1 -> Block 1 (Deskriptoren)
      zlib-Stream 2 -> Block 2 (Nutzdaten)
```

Die zlib-Kompression ist der Grund, warum dieses Format seit 2015 als
ungelöst galt — hinter dem Header sieht alles nach Zufallsbytes aus.

Jeder 4-Byte-Zeiger in Block 1 ist eine Adresse mit Basis **1.000.000.000**;
abziehen ergibt den Offset in Block 2. Die Zeiger liegen **unaligned**.

Block 2 geht restlos auf:

| Bereich | Inhalt |
|---|---|
| Materialien | `nmtl × (frames·16 + 44)` |
| Geo-Structs | `ngeo × frames·4` |
| Mesh-Daten | siehe unten |
| Bones | `nbon × (frames·12 + frames·16)` |

`frames` ist die Länge einer einzigen globalen Zeitleiste (715 in der
Referenzdatei); jeder Clip ist nur ein Bereich darauf.

**Mesh-Puffer**, lückenlos hintereinander:

```
positions  vc * 12   float32 x3
normals    vc * 12   float32 x3   <- bereits Einheitsvektoren
uv         vc *  8   float32 x2
unbekannt  vc *  1   ein Byte pro Vertex
indices    tc *  6   uint16 x3, Triangle-List
skin       vc * 24   Byte 1..4 = Bone-Indices (uint8),
                     Byte 8..23 = vier float32 Gewichte, Summe exakt 1.0
```

**Texturen** ab `atex`: eine **Tabelle** aus `[u32 flags][u32 nameOffset]`,
die Namen liegen dahinter. Den Namen direkt hinter dem Eintrag zu lesen
funktioniert nur zufällig, solange es genau eine Textur gibt.

**Materialien** ab `amtl`, Stride 48: bei `+12` der Index in die Texturliste.

**Gelöst: der vierte Wert pro Frame** ist kein Float, sondern ein `uint32`,
der ausschließlich 0 oder 1 annimmt — ein **Sichtbarkeitsschalter pro Frame**
für den Bone und alles, was daran hängt. Belegt über die Clip-Korrelation:
in `045.x` ist `Bone17` exakt während `single_skill_04_a` und `_04_b` an, in
`156_skin10.x` ist `Bone01_dance_zhibao1` exakt während des gleichnamigen
Clips `dance_zhibao1` an. Die betroffenen Bones sind durchweg Effekt- und
Requisiten-Aufhängungen: `_tx` (特效, Spezialeffekt), `_fx`, `_zhibao`
(至宝, Artefakt-Skin), `Dummy01`.

Vorkommen: `045.x` 4 von 78 Bones, `156_skin10.x` 4 von 128,
`045_skin5_huicheng.x` 36 von 120, `020_skin2.x` und `063_skin7.x` gar keine.

Der Importer legt dafür eine gekeyframte Custom Property **`eg3d_visible`**
am Pose-Bone an, statt den Bone auf Null zu skalieren — so geht nichts
kaputt und der Wert lässt sich als Treiber verwenden.

**Bones, die in jedem Frame kaputt sind.** `144_skin8_huicheng.model` enthält
einen Bone, dessen Keys über die gesamte Zeitleiste NaN sind — es gibt keinen
gültigen Frame zum Kopieren. Solche Bones bekommen eine Identitätstransformation
statt NaN, sonst kollabiert jeder daran gewichtete Vertex.

**Nicht normierte Rotationen.** `156_skin10.x` hat 7 von 128 Bones, deren
Quaternionen in einzelnen Frames Längen bis herunter zu exakt 0,5 haben. Das
Layout ist dort in Ordnung — 121 Bones sind exakt und der Blocktest ergibt
100 % —, es ist also Quelldatenschrott. Der Importer normiert und warnt.

### Zwei Spuradressen je Bone, und wo sie stehen

Ein Bone-Deskriptor enthält **zwei** Block-2-Adressen, 12 Bytes auseinander:
zuerst die Positions-, dann die Rotationsspur. Ihr **Abstand ist die Größe der
Positionsspur** und liefert die Framezahl direkt:

```
A2 - A1 = frames * 12   ->  float32-Positionen
A2 - A1 = frames *  4   ->  Positionen 10:10:10 gepackt
```

Das ersetzt das frühere Raten über Blockgrößen, das bei nicht zusammenhängenden
Spuren gar nicht funktionieren konnte.

Die Adressspalte liegt **nicht immer bei +144**: im Monster-Satz sitzt sie bei
**+148**, die ganze Tabelle ist um vier Bytes verschoben. Der Importer sucht
deshalb die Spalte, die für *jeden* Bone eine gültige Adresse liefert, statt
einen festen Offset anzunehmen.

### GELÖST: die komprimierte Animationsvariante

18 der 44 Monster-Dateien komprimieren die Animation stärker. Beide Spuren sind
jetzt dekodiert.

**Positionen**, 4 Byte je Key: 10:10:10 gegen eine Box, die im Bone-Deskriptor
bei `+88` (Maximum) und `+100` (Minimum) steht, Maske `1023` bei `+112`.

**Rotationen**, 8 Byte je Key — **Achse-Winkel, nicht Quaternion**:

```
bits  0..7    uint8   Drehwinkel in GRAD
bits 16..27   int12   Achse x, Zweierkomplement, negiert
bits 32..43   int12   Achse y
bits 48..59   int12   Achse z
bits 8..15, 28..31, 44..47, 60..63   konstante Tags

theta = A * pi / 360          (Halbwinkel, also A/2 Grad)
axis  = normalisiere(-int12(B), -int12(C), -int12(D))
q     = (axis * sin(theta), cos(theta))
```

Optional folgt auf die Rotationsspur eine `float32x3`-**Scale-Spur**; die
Blockgröße ist dann 24 statt 12 Byte je Frame (4 + 8 + 12).
`tx_030_shenmujiaren_01.x` ist so aufgebaut, dort dekodiert die Rotation zu
100 % unter 1 Grad.

Verifiziert an den Inverse-Bind-Matrizen von **569 Bones aus 13 Dateien**:
Median-Winkelfehler **0,467 Grad**, **99,1 % unter 1 Grad**. Der Rest ist exakt
die Quantisierung des 8-Bit-Winkels in 1-Grad-Schritten.

Zum Vergleich die Kontrollen: Identität 122,0 Grad, Zufallsrotationen
134,6 Grad.

**Der Weg dorthin** führte über zwei Messungen, die den Durchbruch brachten:

1. Der Restfehler nach einer reinen Skalierung je Bone beträgt **0,0002** — die
   Achsen*richtung* war also schon exakt, nur die Länge stimmte nicht. Damit war
   klar, dass B/C/D eine Richtung sind und nicht die Quaternionkomponenten.
2. Die Kennlinie von A gegen das wahre `w` ergab `θ/A = 0,00873` konstant über
   den ganzen Bereich — und 0,00873 rad ist genau `π/360`. Damit war A als
   Winkel in Grad identifiziert.

Ohne die Inverse-Bind-Matrix als Referenz wäre beides nicht messbar gewesen.

### Ältere Formatvariante mit gepackten Positionen

Manche `.x`-Dateien haben nur **23 statt 25 TOC-Einträge** (`083_b.x` etwa) und
speichern die Vertexdaten kompakter. Erkennbar daran, dass bei `+36` keine
Positions-Adresse steht, sondern bei `+40`:

```
+40   Positionen, vc * 4   uint32, 10:10:10 gepackt
+48   Normalen,   vc * 3   int8 x3, NICHT auf 4 Bytes gepolstert
+52   UV, +68 Palettenindex, +76 Indices, +92 Skin   (wie gehabt)
+96   float32 x3  Bounding-Box-Maximum
+108  float32 x3  Bounding-Box-Minimum
+120  1023        die 10-Bit-Maske
```

Position = `min + (bits / 1023) * (max - min)`, je 10 Bit ab Shift 0, 10, 20.
Gegenprobe an `083_b.x`: die dekodierte Bounding Box trifft die im Deskriptor
gespeicherte auf zwei Nachkommastellen, alle Indices liegen im gültigen
Bereich, das Mesh ist nach dem Verschweißen **komplett geschlossen** (0
Randkanten) und das Winding zu 100 % konsistent.

Ohne diese Variante wurde das Mesh mit „no usable position buffer address"
übersprungen — die Datei importierte dann nur Skelett und Animationen.

**Defekte Daten kommen vor.** `156_skin10.x` enthält außerdem einen Bone, dessen
Position und Rotation über 37 aufeinanderfolgende Frames `NaN` sind — bei 127
anderen Bones derselben Datei ist jedes Quaternion exakt Einheitslänge, es ist
also echter Datenschrott. Der Importer ersetzt solche Keys durch den nächsten
gültigen Frame und warnt. Ebenso werden Skin-Slots mit Bone-Index 255
(Füllwert) auf Gewicht 0 gesetzt und Dreiecke mit ungültigen Indices
verworfen.

**Geo-Deskriptoren** ab `ageo`, Stride 124. Jeder Puffer hat seine **eigene
Adresse** — die Offsets aus den Größen hochzurechnen funktioniert nur, solange
keine optionalen Puffer vorkommen:

| Feld | Inhalt |
|---|---|
| `+8` | Namensoffset |
| `+12` | **Mesh**-Index |
| `+16` | **Material**-Index (stimmt bei manchen Dateien zufällig mit `+12` überein, bei `045.x` nicht) |
| `+28` / `+32` | Vertex- und Dreieckszahl |
| `+36` | Positionen, `vc*12` |
| `+44` | Normalen, `vc*12` |
| `+52` | UV, `vc*8` |
| `+60` | **optional**, `vc*4`, liegt zwischen Byte-Puffer und Indices |
| `+68` | Bone-Palettenindex, ein `uint8` pro Vertex |
| `+76` | Indices, `tc*6` |
| `+92` | Skin-Records, `vc*24` |

Bei `156_skin10.x` haben 14 von 21 Meshes den optionalen `+60`-Puffer und
sieben nicht. Rechnet man die Offsets selbst hoch, verschiebt sich bei genau
diesen Meshes der Index-Buffer um `vc*4` Bytes, und man liest Zufallszahlen,
die wie `0xFFFF`-Platzhalter aussehen.

**Bone-Deskriptoren** in Block 1 ab `abon`, Stride 172: bei `+8` der Offset
des Namens, bei `+144` die Block-2-Adresse der Animationsdaten.

Die **Namenstabelle ist gleichzeitig die Hierarchie**: jeder Eintrag ist
`[name NUL][u32 Kind-Index]*`. Ein Kind-Index ist daran erkennbar, dass die
Bytes 2–4 des Wortes null sind, was kein ASCII-Name erzeugen kann. Vorsicht:
vier Nullbytes sind nicht von „Kind 0" unterscheidbar — der Importer behandelt
sie als Padding, was gefahrlos ist, weil Index 0 der alphabetisch erste Name
und damit die Wurzel ist.

**Frame 0 ist die Bind-Pose.** Es gibt keine separate Bind-Matrix. Verifiziert:
transformiert man die dominanten Vertices jedes Bones in dessen lokalen Raum,
clustern sie bei Frame 0 auf 8 % der Modelldiagonale — der beste aller 715
Frames — und die Bone-Positionen liegen 2,64 Einheiten von ihrem gewichteten
Vertex-Schwerpunkt entfernt, bei einem Modell von 98 Einheiten Größe. Das
Skinning bei Frame 0 reproduziert das gespeicherte Mesh mit Abweichung 0,000.

Weil Ruhepose und Animation damit im **selben** Raum liegen, braucht `.x` die
`Align clips to rest pose`-Korrektur nicht — die gilt nur für `.model`.

**Das Quaternion ist konjugiert gespeichert**, es kodiert also die
transponierte Rotation — passend zum Rest des Formats, dessen 4×4-Matrizen
alle Zeilenvektor-Konvention mit der Translation in der letzten Zeile haben.

Diese Falle ist bösartig: bei der Bind-Pose kürzt sie sich weg, ist also in
jedem Test unsichtbar, der nur Frame 0 anschaut. Und sie verschiebt den
**Median** der Kantenlängen kaum. Sichtbar wird sie nur im **Maximum**: ohne
Konjugation streckt sich die schlimmste Kante von `020_skin2.x` während der
Animation auf das **25,5-fache** und die Rüstung zerfällt in Einzelteile; mit
Konjugation auf 8,6 — dieselbe Größenordnung wie beim `.model`-Format.

Deshalb protokolliert der Importer bei aktivierter Diagnose zwei Prüfungen,
die genau diese Klasse von Fehler fangen — für **beide** Formate:

**`animation rigidity`** — Skinning muss starr sein, jede Kante behält in jeder
Pose ihre Länge, **relativ zur Gesamtskalierung des Frames**. Gemessen wird
deshalb das Verhältnis geteilt durch seinen eigenen Median: ein Clip darf die
ganze Figur gleichmäßig skalieren. `234_skin10_huicheng.model` legt Faktor
21,35 auf den Wurzel-Node, wodurch ohne diese Normierung **100 %** der Kanten
als gestreckt galten, obwohl nichts zerreißt. Gemeldet wird das **Maximum** und der **Anteil** der Kanten
über 3×. Der Anteil trennt viel schärfer: mit falscher Quaternion-Konvention
23,2× und 5,30 % der Kanten, mit richtiger 14,1× und 0,38 % — beim Maximum
überlappen die Bereiche, beim Anteil liegt Faktor zehn dazwischen. Gemessene
Referenzwerte: `157_skin11.model` 0,10 %, `334.model` 0,22 %, `020_skin2.x`
0,38 %, kaputt 5,30 %.

Die Bone-Achsen-Prüfung ist entsprechend abgestuft: unter **0,6** ein Fehler
(Zufall liegt bei 0,5), zwischen 0,6 und 0,85 eine Warnung — Effekt-Rigs ohne
Biped landen dort legitim, `045_skin5_huicheng.x` etwa bei 0,778.

**`bone axis alignment`** — beide Formate riggen mit einem 3ds-Max-Biped, dessen
Bones entlang ihrer lokalen **X**-Achse zeigen. Der Importer misst, wie gut jede
Achse zum ersten Kind zeigt. Bei richtiger Rotationskonvention dominiert X klar
(gemessen: `.x` 0,969, `157_skin11` 0,978, `334` 0,951), bei falscher liegen alle
drei nahe 0,5. Diese Prüfung kommt ganz ohne das Mesh aus und sieht damit
Rotationsfehler, die sich in der Bind-Pose wegkürzen.

**Actions** in Block 1 ab `aact`, Stride 90: Name in 80 Bytes, dann
`u16 erster Frame`, `u16 letzter Frame`, jeweils inklusive.

**Animation ohne Clips.** `nact` kann 0 sein, obwohl die Bone-Spuren voll
bespielt sind: `045_skin5_huicheng.x` deklariert keinen einzigen Clip, aber
110 von 120 Bones bewegen sich über 211 Frames, mit Positionsänderungen bis
111 Einheiten. Die Clip-Liste durchzugehen wirft das komplett weg. Findet der
Importer keine Clips, aber Bewegung, legt er einen synthetischen Clip
`full_timeline` über die gesamte Zeitleiste an. Bewegt sich nichts, meldet er
„static asset".

---

### Sammelprüfung über 49 Dateien

Ein Stapeltest über 49 `.model`-Dateien hat drei Dinge zutage gefördert, die
Einzeldateien nicht zeigen:

**Singuläre Bind-Matrizen.** `263_skin5.model` enthält eine Bind-Matrix, die
sich nicht invertieren lässt. Die Prüfroutinen sind daran abgestürzt; sie
überspringen solche Matrizen jetzt und zählen sie im Log.

**Gleichmäßige Skalierung ist keine Zerstörung.** Siehe die Rigiditätsprüfung
oben.

**Dateien ganz ohne Geometrie oder ohne Paletten.**
`149_bat_specialidle_skin13.model` hat 0 Geometrie-Gruppen und nur einen Clip —
eine reine Animationsdatei. `101_skin12_huicheng2.model`,
`156_skin17_huicheng_tx.model` und die `308_*`-Dateien haben Gruppen, aber
0 Paletten: reine Effekt-Assets ohne Skinning.

Nach den Korrekturen liegen alle 49 Dateien im grünen Bereich, der schlechteste
Rigiditätswert ist 1,02 % (`112_160.model`).

### Versteckte Requisiten: Skalierung auf nahezu null

Die Engine blendet Requisiten nicht über ein Sichtbarkeitsflag aus, sondern
indem sie den tragenden Bone auf fast null skaliert. Bei `336_skin1.model`:

```
Bone001  <- Bip001 R Hand    Scale 0.001   in ALLEN 31 Clips
Bone002  <- Bip001 L Hand    Scale 0.001   in ALLEN 31 Clips
Bone029..032                 Scale 1.0     (Kinder von Bone001/002)
```

Es ist genau **ein Key** pro Clip, keine Animation über die Zeit — also ein
Schalter, den die Engine zur Laufzeit setzt. Da Skalierung sich in der
Hierarchie fortpflanzt, kollabieren auch die vier Kind-Bones mit; 70,6 % der
Waffen-Vertices hängen direkt an den beiden Null-Bones, der Rest an deren
Kindern.

Das erklärt eine sonst verwirrende Beobachtung: **ohne** Animation sind die
Waffen sichtbar, **mit** Animation verschwinden sie. Ohne Clips greift kein
Scale-Kanal, und in der Ruhepose ist bei diesen Bones gar keine Skalierung
gesetzt. Derselbe Effekt tritt im 3ds-Max-Importer auf und ist auch dort
korrekt.

Die Option **Ignore zero-scale bones** (Standard aus) setzt solche Scale-Keys
auf 1 zurück. Gemessen an `single_attack_attcom_1`: die Waffe wächst von
Größe 0,88 auf 2,12, und der Render zeigt zwei Schwerter, die sauber in beiden
Händen sitzen und dem Schwung folgen. Die Schwelle ist über
**Zero-scale threshold** einstellbar (Standard 0,01).

### Offen: der Koordinatenraum starrer Requisiten

Nodes ohne Bone-Palette tragen starre Geometrie — Waffen und Effektkarten.
Ihr Koordinatenraum ist **nicht verstanden**. Gemessen an `039_skin8.model`,
Gruppe 8 (`112_skin4_szt`, 8 Vertices, Material `avmesh` ohne Textur):

| | Bounding Box |
|---|---|
| Rohkoordinaten | −1,3 … 1,3 × 0,01 … 4,54 |
| mit Node-Weltmatrix | y **6,71 … 8,42** |
| Körper zum Vergleich | y −0,51 … 1,01 |

Beide Varianten liegen daneben; der Trägerbone `Bone127` sitzt selbst bei
y = 7,33. Die Kette hängt in einem eigenen System, das sich nicht ohne
Weiteres in den Mesh-Raum überführen lässt.

Seit 2.3.0 gibt es dafür die Option **Rigid props**, standardmäßig **aus**.
Damit sind die Animationen wieder ruhig; die Requisiten fehlen, wie vor
Version 1.12.0 auch.

**Die geskinnten Meshes sind davon nicht betroffen.** Über den `dance`-Clip
von `039_skin8.model` einzeln gemessen:

```
g0_s0  15220 Verts   0.00%     g3_s0    626 Verts   0.00%
g1_s0    828 Verts   0.00%     g4_s0    264 Verts   0.00%
g2_s0  12884 Verts   0.05%     g5/g6                0.00%
```

### Keyframes müssen LINEAR sein

Blender legt Keyframes standardmäßig als **Bézier mit automatischen Handles**
an. Die Handles ergeben sich aus den Nachbarkeys, deshalb überschwingt die
Kurve überall dort, wo sich der Keyabstand ändert — der Wert verlässt den
Bereich, den seine eigenen Keys aufspannen. Die Quelldaten haben keine solche
Weichzeichnung; sie sind eine schlichte Folge abgetasteter Posen.

Sichtbar wird das, wenn in einer Bone-Kette ein Glied dicht und ein anderes
dünn gekeyt ist. In `336_skin1.model` haben die Beinknochen 46
Rotations-Keys im 33-ms-Takt, `Bip001 Spine` dagegen nur **6**, auf den Frames
0, 8, 22, 25, 40 und 45. Nachgerechnet an genau diesem Kanal verlässt die
Bézier-Kurve den Wertebereich ihrer Keys um bis zu **4,5 %** — und jeder
Spine-Key ließ den Fuß zucken.

Das erklärt auch, warum `.x` nie betroffen war: dort ist **jeder** Frame
gekeyt, die Handles haben nichts zu extrapolieren.

Seit 2.9.0 setzt der Importer jede erzeugte Kurve auf `LINEAR`.

### Die Bind-Matrizen tragen Skalierung — Blender-Bones können das nicht

Das war die Ursache für schwankende Lauf-Animationen.

Die Inverse-Bind-Matrizen der `.model`-Dateien sind **nicht orthonormal**. Bei
`039_skin8.model` steckt eine gleichmäßige Skalierung von **1,6881** darin.
Ein Blender-Bone kann keine Skalierung tragen: `edit_bone` wird aus Kopf,
Spitze und Roll gebaut, `bone.matrix_local` ist immer orthonormal, und der
Importer verwirft die Skalierung beim Anlegen korrekt mit `to_quaternion()`.

Die **Animation** wurde aber gegen die *rohen*, skalierten Matrizen gerechnet.
In `inv(bind_eltern) @ bind_kind` skaliert die Elternmatrix die Translation des
Kindes mit — Blenders Bone hat diesen Faktor nicht. Gemessen:

| | roh vs orthonormal |
|---|---|
| Rotation | **0,000°** — identisch |
| Position | Median 0,016 · **max 0,573** bei 4,28 Modellgröße |

Ein Positionsfehler von 13 % der Modellgröße, der pro Bone und Frame variiert:
genau das sieht man als Pendeln.

**Der Gegenbeweis** steckt in den Dateien selbst:

| Datei | Skalierung | Symptom |
|---|---|---|
| `157_skin11.model` | 1,0000 | war immer sauber |
| `110_skin5.model` | 1,0000 | unauffällig |
| **`039_skin8.model`** | **1,6881** | schwankte |
| `067_skin4_huicheng_2.model` | 0,5987 | betroffen |
| `112_skin4.model` | 0,9644 | betroffen |

Seit 2.6.0 wird die Ruhematrix für die Animation genauso orthonormalisiert wie
beim Anlegen der Bones. Das allein reicht aber **nicht**: Blender berechnet die
Verformung als `pose_world @ rest_orth⁻¹`, richtig wäre `anim_world @
rest_raw⁻¹`. Gleichsetzen ergibt eine Korrektur **von rechts**, pro Bone:

```
pose_world = anim_world @ rest_raw⁻¹ @ rest_orth
```

Ohne sie ist die Animation zwar ruhig, das Mesh verformt sich aber im falschen
Maßstab — gemessen an `039_skin8.model` 0,102 im Median und 0,297 maximal bei
4,28 Modellgröße. Mit der Korrektur: **exakt 0,000000**.

Der 3ds-Max-Importer desselben Projekts macht es genauso und nennt es dort
„Korrektur von RECHTS". Seit 2.6.1 gilt das für beide Formate.

### Keys an den Quellzeiten statt Resampling

Bis 2.4.0 hat der Importer die Kanäle bei `f / fps * 1000` **neu abgetastet**
und selbst interpoliert. Das war die Ursache für schwankende Lauf-Animationen.

Die Dateien speichern Keyzeiten als **gerundete Millisekunden** — 33, 66, 100 —
die als Frames gemeint sind: `33 ms × 30 / 1000 = 0,99`, also Frame 1. Wer bei
`f × 33,333 ms` abtastet, landet zwischen den Quellkeys und legt eine **zweite
Interpolation** über die von Blender.

Seit 2.5.0 werden die Keyzeiten einmal auf ganze Frames gerundet. Der Wert wird
dann **auf dem Frame-Raster interpoliert** — nicht in Millisekunden.

Beides muss gleichzeitig stimmen, und je eine Hälfte falsch zu machen ist
sichtbar:

* **Auf einem Frame mit eigenem Key** muss der Wert exakt dieser Key sein. Bei
  `f × 1000/fps` abzutasten driftet gegen das 33-ms-Raster der Datei — das ließ
  Lauf-Zyklen schwanken.
* **Zwischen den eigenen Keys** muss interpoliert werden. In 2.5.0 und 2.6.x
  habe ich stattdessen den letzten Key gehalten. Bei dichten Kanälen fällt das
  nicht auf, bei dünnen wird eine Treppe daraus: in `bat_idle` hat ein Kanal
  nur auf **9 %** der Frames einen eigenen Key, in `dance` einer auf **2 %**.
  Genau deshalb zitterten alle Clips außer den dicht gekeyten Lauf-Zyklen.

Auf dem Frame-Raster zu interpolieren erfüllt beides: exakt auf den Keys
(gemessen 1,000000), glatt dazwischen, ohne Millisekunden-Drift.
Gemessen an `039_skin8.model`, Abweichung vom jeweiligen Quellkey:

| Clip | alt (Resampling) | neu (Quellkeys) |
|---|---|---|
| `bat_run` | Median 0,150° · max **4,49°** | Median 0,000° · max **0,04°** |
| `single_run` | Median 0,107° · max **6,04°** | Median 0,000° · max **0,05°** |

Das Snapping ist verlustfrei: die Quellkeys liegen im Median 0,12 Frames von
einem ganzen Frame entfernt, **keiner** weiter als 0,25.

Dieselbe Lösung nutzt der 3ds-Max-Importer desselben Projekts, dessen
Animationen von Anfang an sauber waren — der Kommentar dort lautet „zwei
Interpolationen übereinander wären schlechter als eine".

### Gelöst: die booleschen Kanäle

Der Kanal-Deskriptor hat bei `[6][1]` einen **Werttyp**, den ich lange
ignoriert habe. Gemessen über 136.395 Kanäle in 51 Dateien:

| Typ | Format | verwendet für |
|---|---|---|
| 0 | `float32` | Position, Rotation, Scale, Materialfarben |
| 6 | `uint8` | `active`, `enable`, `rendererenable` |

Alles als `float32` zu lesen macht aus den booleschen Spuren Unsinn: die Bytes
`01 00` eines `active`-Kanals kamen als `9,18e-41` heraus statt als `[1, 0]`.

**Diese Kanäle schalten ganze Node-Teilbäume.** In `039_skin8.model` trägt der
Node `144_skin10_dance` den **kompletten zweiten Charakter** — 16.636 Vertices
in den Gruppen 2 bis 8 — und ist nur im Clip `dance` eingeschaltet, dort von
0 bis 3433 ms. In allen 16 anderen Clips steht er auf 0.

Ohne Auswertung bleibt dieser zweite Charakter in **allen 17 Clips** sichtbar
und überlagert den ersten. Der Importer keyframed jetzt `hide_viewport` und
`hide_render` der betroffenen Objekte.

Betroffen sind **19 von 50** geprüften `.model`-Dateien, von einem einzelnen
Kanal (`138_skin11_huicheng_a`) bis zu 402 (`289_skin2`).

### Mehrere Charaktere, Requisiten und Instanzen in einer `.model`

`039_skin8.model` ist ein Doppelmodell: 281 Nodes, **zwei komplette Bipeds**
(`Bip001` mit 66, `Bip002` mit 69 Nodes), 27 Geometrie-Gruppen und nur
7 Bone-Paletten. Daraus folgen drei Regeln, die einfachere Dateien nicht
sichtbar machen:

**Die Palette steht am Node, nicht an der Gruppe.** Ein Mesh-Node nennt in
Feld 6 seine Geometrie-Gruppe und in Feld 7 seine Bone-Palette. Bei Dateien
mit gleich vielen Gruppen und Paletten sind beide Zahlen zufällig identisch —
hier nicht, und wer über die Gruppennummer indiziert, lässt 20 Submeshes ohne
Skinning.

**Eine Gruppe kann an mehreren Nodes hängen.** Die Gruppen 7 und 8 (`144_wuqi`,
eine Waffe, und `112_skin4_szt`) werden je zweimal instanziert, an `Bone127`
und `Bone129`. Der Importer legt dafür zwei Objekte mit Suffix `_at_<node>` an.

**Nodes ohne Palette tragen starre Geometrie.** Sie hat keine Gewichte in der
Datei, sondern reitet auf ihrem Node. Der Importer bindet jeden Vertex mit
Gewicht 1 an den zugehörigen Bone, damit der normale Armature-Pfad sie
mitnimmt.

**Gruppen ohne Node-Referenz sind Partikel-Vorlagen.** 18 der 27 Gruppen
werden von keinem Node benutzt; ihre Materialien sind vom Typ `ezParticle`,
und die Node-Extras enthalten Partikel-Parameter wie `startSize` und
`gravityModifier`. Die Engine erzeugt sie zur Laufzeit, sie sind keine
platzierte Geometrie, und der Importer überspringt sie mit Hinweis im Log.

### „File too small" und ähnliche Meldungen

Wenn der Importer meldet, eine Datei sei zu klein oder beginne nicht mit
`EG3D`, liegt der Fehler **in der Datei**, nicht im Importer.
`020_skin3.model` etwa war genau **1 Byte** groß und enthielt das ASCII-Zeichen
`1`, während die zugehörige `020_skin3.dds` mit 1 MB vollständig vorlag — die
Extraktion aus dem Spiel war schiefgegangen. Solche Dateien müssen neu
entpackt werden.

Der Importer erkennt außerdem, wenn eine `.x`-Datei versehentlich `.model`
heißt, und sagt das explizit; das Format wird ohnehin an der Signatur erkannt,
nicht an der Endung.

## Regressionsprüfung

Der Importer wird gegen **100 Dateien** geprüft — 50 `.x` und 50 `.model` —, und
zwar nicht nur auf „läuft durch", sondern inhaltlich: Indices im gültigen
Bereich, Bone-Achsen-Ausrichtung, Skinning-Rigidität und tatsächliche Bewegung.

**Der Animationspfad wird eigens geprüft.** Die Prüfung bildet Blenders eigene
Rechnung nach — orthonormale Ruhematrix, Korrektur von rechts, Interpolation
auf dem Frame-Raster, dann `pose_world @ rest_orth⁻¹` — und vergleicht das
Ergebnis Vertex für Vertex gegen die Referenz `anim_world @ inverse_bind`.
Über 45 `.model`-Dateien mit Clips ist die größte Abweichung **0,000000000**.

Dieselbe Prüfung läuft über **50 `.x`-Dateien**, ebenfalls mit Abweichung
0,000000000.

Ohne diese Prüfungen wären die Fehler der Versionen 2.5 bis 2.7 nicht
aufgefallen: die alte Regression testete nur Parser und Diagnose, nicht die
Animation. In 2.7.0 hat ein einzelner solcher Fehler den gesamten Import
zerstört — im `.x`-Pfad ist `rest_raw` eine **Liste**, im `.model`-Pfad ein
**Dictionary**. Der Aufruf `rest_raw.items()` warf dort einen `AttributeError`,
und der Import brach ab, bevor eine einzige Action entstand. Das Log endete
mitten im Mesh-Aufbau, ohne Fehlerzeile. Die `.x`-Animationsprüfung bildet
diese Struktur jetzt mit nach.

### Key-Kollisionen beim Runden auf Frames

Zwei Quell-Keys können auf denselben Frame fallen; dann geht einer verloren.
Gemessen über 50 Dateien:

| Bildrate | verlorene Keys, Median | schlimmste Datei |
|---|---|---|
| 30 fps | 4,45 % | 14,7 % (`197_huicheng_skin5`) |
| 60 fps | 0,28 % | 0,87 % |
| 120 fps | 0,00 % | 0,00 % |

Der Importer meldet den Anteil jetzt pro Clip — über 2 % als Warnung. Wer die
Keys vollständig braucht, stellt **FPS** auf 60 oder 120.

### Kaputte Bind-Matrizen

`263_skin5.model` enthält zwei Bind-Matrizen, die **komplett aus Nullen**
bestehen (`Bone043` ist eine davon). Das ist Datenschaden in der Datei. Der
Importer erkennt sie, überspringt ihre Skalierungskorrektur und warnt, statt
mit einer stillschweigend falschen Einheitsmatrix weiterzurechnen.

```
Regression: 100 Dateien (50 .x, 50 .model)
   Bone-Achse  median 0.951 (min 0.592)
   Rigiditaet  median 0.0008 (max 0.0093)
   Abbrueche 0 | Parser-Fehler 0 | Indices ausserhalb 0
```

Drei Randfälle, geprüft und für unbedenklich befunden:

**`monster_qizhi_01.x`, Bone-Achse 0,592.** Ein Fahnen-Rig mit 13 Wurzel-Bones
und Namen wie `Bone01bao` — kein Biped, die Achsenprüfung ist dort nicht
aussagekräftig. Die Datei ist rein positionsanimiert (0,53 gegen 0,02
Rotation).

**„Statische" Dateien mit Clips.** `common_5v5by01.x` und die `max_totem`-Paare
zeigen kaum Rotation, aber deutliche Translation. Fahnen und Totems werden
verschoben, nicht gedreht. Die Bewegungskontrolle misst deshalb beides.

**Winding 0 % bei `293_skin2_huicheng.model / g7_s0`.** Eine flache Scheibe
(z = 0, Radius 4,4) mit `ezParticle`-Material, deren Dreiecke abwechselnd
orientiert sind — ein Boden-Decal. Bei beidseitigem Rendering folgenlos.

**Clips jenseits der Zeitleiste.** `tx_030_shenmujiaren_01.x` deklariert einen
Clip bis Frame 45, hat aber nur 41 Frames (Blockgröße 984 = 41 × 24). Das ist
ein Fehler in der Quelldatei; der Importer kappt und warnt, statt abzulehnen.

## Format-Notizen `.model` (Kurzfassung)

Die Langfassung steht im Docstring von `eg3d_parse.py`. Das Wichtigste:

```
0x00  'EG3D'
0x04  u32  version (=4)
0x08  u32  mainSize
0x0C  Binärblock (mainSize Bytes)      <-- Basis für ALLE Offsets
      JSON-Metadaten (UTF-8)
```

**Alle Offsets im JSON sind relativ zum Binärblock, der bei Byte 12
beginnt:** `absolut = 12 + offset`. Werden sie als absolute Dateioffsets
gelesen, verschiebt sich alles um 12 Bytes — und weil 12 Bytes je nach
Attribut 1,5 bis 6 Elemente sind, wird das Mesh aus fremden Vertices gebaut.
Symptome: Löcher, Bridge-Triangles, „zersplitterter" Look, `|q| ≈ 0.14` beim
Skelett, Weights ≠ 1, ein scheinbarer „6-u16-Garbage-Header" am Index-Buffer
und ein scheinbarer „versteckter 12-Byte-Header" vor jedem Animations-Array.
Nichts davon existiert.

| Sektion | Inhalt |
|---|---|
| `meta[0]` | `{generator, version, leftHandCoord}` |
| `meta[1]` | Scene-Root |
| `meta[2]` | Materialien `[name, type, props]` |
| `meta[3]` | Geometrie: Gruppen → Submeshes |
| `meta[4]` | Bone-Paletten + Offset der Inverse-Bind-Matrizen |
| `meta[5]` | Nodes (Hierarchie + lokale TRS = Frame 0 des Idle-Clips) |
| `meta[6]` | Texturen `{uri}` |
| `meta[7]` | Animationsclips |

**Submesh** = `[materialIndex, vertexCount, [attribute...], [idxOffset, idxCount]]`
**Attribut** = `[attrId, typeCode, ?, components, normalizeFlag, dataOffset, scaleOffset, biasOffset]`

Typcodes: `0` = uint8, `1` = unorm8, `2` = uint16, `3` = int8, `4`/`5` = float16.
`int8`/`uint8` mit < 4 Komponenten sind auf 4 Bytes gepaddet.
`normalizeFlag == 1` → durch 255 / 127 / 65535 teilen.
Positionen und UV: `wert = bias + roh * scale`, beide Vektoren liegen direkt
hinter den Daten, Offsets stehen im Deskriptor (Felder 6 und 7 — die stimmen,
man muss nicht nach plausiblen Floats scannen).

**Index-Buffer:** plain Triangle-List, uint16, `idxCount` ist die Anzahl der
Indices (nicht Bytes), kein Header zu überspringen.

**`meta[4][g]` = `[[nodeIndex...], byteOffset]`.** Der Offset zeigt auf
`len(bones)` Inverse-Bind-Matrizen à 64 Byte, **Zeilenvektor-Konvention**
(Translation in der letzten *Zeile*) → transponieren, dann invertieren ergibt
die Bind-Weltmatrix. Die Bone-Indices im Vertex sind **lokale** Indices in
diese Liste, nicht globale Node-Indices.

**Nodes:** `[name, translationOffset, rotationOffset, scaleOffset, ?,
children, meshGroup, ?, extras, flags]` — Translation 3×f32, Rotation 4×f32
als `x,y,z,w`, Scale 3×f32. `null` = Identität.

**Animation:** Clip = `[name, [channel...]]`, Channel =
`[nodeIndex, kind, 0, keyCount, components, [timeOffset,type], [valueOffset,type]]`.
`kind`: 0 = Position (3), 1 = Rotation-Quaternion (4, `x,y,z,w`), 2 = Scale (3).
Zeiten sind **uint16-Deltas in Millisekunden**, erster Eintrag 0 — typische
Werte 33/66/100/133 (= Vielfache von 1/30 s). Werte sind float32.

---

## Dateien im Paket

```
io_scene_eg3d/
├─ blender_manifest.toml   Extension-Manifest (4.2+)
├─ __init__.py             Operator, Properties, UI, Registrierung
├─ eg3d_parse.py           Format-Parser (kein bpy, standalone lauffähig)
├─ eg3d_diag.py            Topologie-/Loch-Diagnose
├─ eg3d_build.py           Blender-Datenaufbau (Mesh, Material, Rig, Anim)
├─ eg3d_log.py             Logger (Konsole / Text-Datablock / Datei)
└─ README.md               diese Datei
```

Getestet gegen `157_skin11.model` (4 Submeshes, 21388 Dreiecke, 139 Nodes,
113 geskinnte Bones, 17 Clips) und `334.model` (mehr Submeshes, Vertexfarben,
28 Clips).

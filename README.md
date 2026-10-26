# uploadLanguage

Genera JSON de ayuda traducida a partir de la plantilla inglesa de cada juego y
DOCX bilingües. Funciona de forma independiente en Windows y macOS.

## 1. Instalación y dependencias

Necesitas **Python 3.10 o superior**. Abre la terminal dentro de `uploadlanguage`.
El entorno virtual se llama **`.venv`**.

### Windows (CMD)

```cmd
py -3 --version
py -3 -m venv .venv
.venv\Scripts\python.exe -m pip install -r requirements.txt
run.cmd
```

### macOS (Terminal)

```bash
python3 --version
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt
chmod +x run.sh run.command
```

Si `python3` es inferior a 3.10, instala una versión compatible y úsala para
crear el entorno, por ejemplo: `python3.12 -m venv .venv`.

`requirements.txt` instala **python-docx** para leer documentos y **gdown** para
Google Drive. La instalación requiere internet. Los lanzadores detectan `.venv`
sin activarlo. Créalo una vez por equipo; no copies el entorno entre Windows y Mac.
Si ya existe con un Python antiguo, renómbralo antes de crear el nuevo.
Después de actualizar dependencias, repite el comando de instalación de requisitos.

## 2. Configuración

Prepara las carpetas dentro del proyecto:

```text
uploadlanguage/
├── files/                             DOCX individuales
├── template/
│   ├── info.json                      Plantilla inglesa obligatoria
│   └── jackpotpages.json              Plantilla opcional
├── modules/                           Código del programa
├── config.json
└── output/                            Resultados generados
```

En `config.json`, conserva estos valores y el resto de propiedades existentes:

```json
{
  "documents": "files",
  "googleDriveUrl": "URL_GOOGLE_DRIVE",
  "templates": "template",
  "matching": "position",
  "compareEnglish": true,
  "layout": "template",
  "output": "output"
}
```

Las rutas son relativas a `config.json`. Para cambiar de juego, reemplaza sus
plantillas inglesas y sus DOCX; no necesitas colocar esta herramienta en el juego.

Opcionalmente añade `"googleDriveUrl": "https://drive.google.com/drive/folders/ID"`.
La carpeta y los DOCX deben ser accesibles públicamente mediante el enlace.
Drive se consulta **solo si `files/` no contiene ningún DOCX reconocido**;
las descargas son temporales. Elimina esa propiedad para usar solo archivos locales.

Cada DOCX debe contener tablas con una columna `INGLÉS`, `ENGLISH` o `ENG` y,
a su derecha, la traducción; incluye títulos y reglas en el orden de la plantilla.
La numeración es opcional: se asigna consecutivamente por orden.

Detalles de lectura de los DOCX:

- Se lee también el texto dentro de controles de contenido (DOCX exportados
  desde Google Docs) y de cambios registrados insertados.
- Las filas repetidas por celdas combinadas verticalmente se leen una sola vez.
- Una celda con varias líneas (p. ej. una regla con sub-viñetas) se divide en
  varias reglas si así encaja con la plantilla; las sub-viñetas conservan su sangría.
- Los marcadores pueden tener otra numeración que la plantilla (`[SYMBOL_15]` →
  `sym_16.png`): se aprende de las filas alineadas con la plantilla inglesa.
- Se corrigen errores de marcadores que existen en la fila inglesa
  (`SYMBOL_1]`, `[[X]]`, `[SIMBOL_13]`, `[ÍCONE_GRAND_JACKPOT]`) y se informa en `report.json`.
- Las notas `ENG: texto` / `IDIOMA: traducción` fuera de las tablas bilingües
  traducen los textos de la plantilla fuera de `rules` (p. ej. títulos de `payTables`)
  cuando el inglés coincide exactamente; se respeta el número de líneas inglés.

El idioma se reconoce por los primeros tres caracteres del nombre, ignorando
espacios iniciales y mayúsculas. No coloques dos documentos para el mismo idioma.

| Prefijo | Código | Prefijo | Código |
|---|---|---|---|
| GER | deu | GRE | ell |
| FRE | fra | IND | ido |
| ITA | ita | JAP | jpn |
| CAM | kmb | SOU | krs |
| MAL | mly | POR | por |
| RUS | rus | THA | tha |
| TUR | tur | VIE | vie |

## 3. Qué hace el programa y cómo usarlo

La **plantilla inglesa define la estructura, los recursos y los estilos**.
El programa extrae títulos, subtítulos y reglas de los DOCX, incorpora las
traducciones y distribuye las páginas según el formato de esa plantilla.
Con `matching: position`, asocia por orden cuando coinciden las cantidades;
si difieren, busca por título o contenido inglés y lo informa.
Si una traducción está vacía, sigue en inglés o tiene símbolos incompatibles,
conserva el texto inglés y registra una advertencia.

### `compareEnglish`: con o sin comparación con el inglés

| Valor | Comportamiento |
|---|---|
| `true` (por defecto) | Compara cada fila con el inglés de la plantilla: cantidad de reglas, texto inglés y símbolos. Si algo no coincide, conserva el inglés. |
| `false` | Extrae los textos de la columna del idioma **tal como están** y los inserta en orden, sin comparar con su inglés ni con la plantilla. |

Con `compareEnglish: false`:

- Se insertan todas las filas traducidas, aunque la columna inglesa esté vacía,
  sea distinta de la plantilla o haya más o menos filas que reglas inglesas.
- La plantilla inglesa solo aporta el formato: viñetas, sangrías, espaciado,
  ancho de línea, número de líneas por página y subtítulos. Los textos sobrantes
  usan el formato de la última regla inglesa.
- Los marcadores se convierten por su nombre (`[SYMBOL_8A]` → `##sym_8a.png##`,
  o con `tokens`). Los que no se reconocen se insertan tal cual y se avisa en `report.json`.
- Las filas sin traducción se omiten. Se sigue avisando si el número de textos
  no coincide con el de reglas inglesas, pero sin descartar nada.

| Acción | Windows (CMD) | macOS (Terminal) |
|---|---|---|
| Todos los idiomas disponibles | `run.cmd` | `./run.sh` |
| Un idioma | `run.cmd --lang por` | `./run.sh --lang por` |
| Varios idiomas | `run.cmd --lang deu,fra,ita` | `./run.sh --lang deu,fra,ita` |
| Borrar resultados | `run.cmd --reset` | `./run.sh --reset` |

En Mac también puedes abrir `run.command` con doble clic.
`--reset` elimina únicamente `output/`; ejecútalo separado de `--lang`.

Revisa estos resultados antes de copiar los JSON al juego:

- `output/lang/{idioma}/info/`: JSON traducidos.
- `output/extracted.json`: contenido extraído de los DOCX.
- `output/extracted-texts.json`: notas `ENG:` / traducción extraídas para textos fuera de reglas.
- `output/report.json`: errores y advertencias.
- `output/preview.html`: vista aproximada; comprueba el ajuste final en el juego.
- `output/template-manifest.json`: plantillas y documentos utilizados.

### Estructura del código

| Archivo | Responsabilidad |
|---|---|
| `upload_language.py` | CLI, plantillas, traducción de reglas, paginación y salidas |
| `modules/extraction.py` | Búsqueda de DOCX (local / Google Drive) y extracción de tablas bilingües |
| `modules/text_processing.py` | Normalización de textos, marcadores de símbolos y ajuste de líneas |
| `modules/languages.py` | Prefijos, códigos de idioma y exclusiones |
| `modules/common.py` | Lectura/escritura JSON y entradas de `report.json` |

No modifica los DOCX ni las plantillas originales. Procesa los 14 idiomas de la
tabla; excluye inglés, español y ambos chinos, y no lee PDF ni DOCX compartidos.

import { readdirSync, readFileSync, statSync } from "node:fs";
import { join, relative } from "node:path";
import { describe, expect, it } from "vitest";
import { webRoot } from "./css";

// Story 1.4 (UX-DR1, UX-DR38): colours live only in src/styles/tokens.css, so only the Forest
// palette, white and the DESIGN.md derived shades can reach the screen.
const TOKENS_FILE = "src/styles/tokens.css";
const SKIPPED_DIRS = new Set([
  "node_modules",
  "dist",
  "coverage",
  "playwright-report",
  "test-results",
  "tools",
]);
const CHECKED_EXTENSIONS =
  /\.(css|scss|less|ts|tsx|js|jsx|mjs|cjs|html|json|svg)$/;
const STYLESHEET = /\.(css|scss|less)$/;

// CSS named colours (CSS Color 4). Keywords that aren't a colour of their own stay allowed:
// transparent, currentColor, inherit, initial and unset.
const NAMED_COLOURS = new Set(
  (
    "aliceblue antiquewhite aqua aquamarine azure beige bisque black blanchedalmond blue " +
    "blueviolet brown burlywood cadetblue chartreuse chocolate coral cornflowerblue cornsilk " +
    "crimson cyan darkblue darkcyan darkgoldenrod darkgray darkgreen darkgrey darkkhaki " +
    "darkmagenta darkolivegreen darkorange darkorchid darkred darksalmon darkseagreen " +
    "darkslateblue darkslategray darkslategrey darkturquoise darkviolet deeppink deepskyblue " +
    "dimgray dimgrey dodgerblue firebrick floralwhite forestgreen fuchsia gainsboro ghostwhite " +
    "gold goldenrod gray green greenyellow grey honeydew hotpink indianred indigo ivory khaki " +
    "lavender lavenderblush lawngreen lemonchiffon lightblue lightcoral lightcyan " +
    "lightgoldenrodyellow lightgray lightgreen lightgrey lightpink lightsalmon lightseagreen " +
    "lightskyblue lightslategray lightslategrey lightsteelblue lightyellow lime limegreen linen " +
    "magenta maroon mediumaquamarine mediumblue mediumorchid mediumpurple mediumseagreen " +
    "mediumslateblue mediumspringgreen mediumturquoise mediumvioletred midnightblue mintcream " +
    "mistyrose moccasin navajowhite navy oldlace olive olivedrab orange orangered orchid " +
    "palegoldenrod palegreen paleturquoise palevioletred papayawhip peachpuff peru pink plum " +
    "powderblue purple rebeccapurple red rosybrown royalblue saddlebrown salmon sandybrown " +
    "seagreen seashell sienna silver skyblue slateblue slategray slategrey snow springgreen " +
    "steelblue tan teal thistle tomato turquoise violet wheat white whitesmoke yellow yellowgreen"
  ).split(" "),
);
const SKIPPED_FILES = new Set([
  TOKENS_FILE,
  "package.json",
  "package-lock.json",
]);

// A hex colour (#rgb, #rgba, #rrggbb, #rrggbbaa) or a CSS colour function.
const COLOUR_PATTERN =
  /(?<![\w&])#(?:[0-9a-fA-F]{8}|[0-9a-fA-F]{6}|[0-9a-fA-F]{3,4})(?![\w-])|\b(?:rgba?|hsla?|hwb|lab|lch|oklab|oklch|color)\(/g;

type StrayColour = { file: string; line: number; value: string };

function findStrayColours(file: string, text: string): StrayColour[] {
  const found: StrayColour[] = [];
  const stylesheet = STYLESHEET.test(file);
  // Comments can't set a colour; blank them but keep their newlines so line numbers hold.
  const declarations = stylesheet
    ? text.replace(/\/\*[\s\S]*?\*\//g, (c) => c.replace(/[^\n]/g, " "))
    : "";
  const declarationLines = declarations.split(/\r?\n/);
  text.split(/\r?\n/).forEach((content, index) => {
    for (const match of content.matchAll(COLOUR_PATTERN)) {
      found.push({ file, line: index + 1, value: match[0] });
    }
    if (stylesheet) {
      for (const value of namedColours(declarationLines[index] ?? "")) {
        found.push({ file, line: index + 1, value });
      }
    }
  });
  return found;
}

/** Named colours in the value of a `property: value` declaration on this line. */
function namedColours(line: string): string[] {
  const declaration = /(?:^|[{;])\s*-{0,2}[a-zA-Z][\w-]*\s*:([^;{}]*)/g;
  const found: string[] = [];
  for (const match of line.matchAll(declaration)) {
    // Whole words only: `--color-white` or `white-space` is not the colour white.
    for (const word of (match[1] ?? "").split(/[^a-zA-Z-]+/)) {
      if (NAMED_COLOURS.has(word.toLowerCase())) found.push(word);
    }
  }
  return found;
}

function sourceFiles(dir: string): string[] {
  return readdirSync(dir).flatMap((name) => {
    const path = join(dir, name);
    if (statSync(path).isDirectory()) {
      // Dot-folders at the web/ root are tool state; under src/ they are checked like the rest.
      const toolState = relative(webRoot, dir) === "" && name.startsWith(".");
      return SKIPPED_DIRS.has(name) || toolState ? [] : sourceFiles(path);
    }
    return CHECKED_EXTENSIONS.test(name) ? [path] : [];
  });
}

describe("1.4 colour tokens", () => {
  it("story 1.4: no colour value appears outside the tokens file", () => {
    const stray = sourceFiles(webRoot)
      .map((path) => relative(webRoot, path).split("\\").join("/"))
      .filter((file) => !SKIPPED_FILES.has(file))
      .flatMap((file) =>
        findStrayColours(file, readFileSync(join(webRoot, file), "utf8")),
      );

    const report = stray
      .map((s) => `${s.file}:${s.line} ${s.value}`)
      .join("\n");
    expect(
      report,
      `Colours outside ${TOKENS_FILE}; use a token instead:\n${report}`,
    ).toBe("");
  });

  it("story 1.4: the check names the file and line of a stray colour", () => {
    // Built from pieces so this file holds no colour literal itself.
    const hex = "#" + "B40838";
    const fn = "rg" + "ba(0, 0, 0, 0.5)";
    const text = `.a {\n  color: ${hex};\n}\n.b { box-shadow: 0 0 1px ${fn}; }`;

    expect(findStrayColours("src/x.css", text)).toEqual([
      { file: "src/x.css", line: 2, value: hex },
      { file: "src/x.css", line: 4, value: "rg" + "ba(" },
    ]);
  });

  it("story 1.4: a named colour in a stylesheet declaration is a stray colour", () => {
    const text = [
      "/* a comment: " + "red */",
      ".a {",
      "  color: " + "rebeccapurple;",
      "  border: 1px solid " + "Red;",
      "  white-space: nowrap;",
      "  background: transparent;",
      "  color: currentColor;",
      "  color: var(--color-white);",
      "}",
    ].join("\r\n");

    expect(findStrayColours("src/x.scss", text)).toEqual([
      { file: "src/x.scss", line: 3, value: "rebecca" + "purple" },
      { file: "src/x.scss", line: 4, value: "R" + "ed" },
    ]);
    // Copy in TypeScript is not a declaration.
    expect(findStrayColours("src/strings.ts", 'label: "Red flag"')).toEqual([]);
  });

  it("story 1.4: element ids and entities are not mistaken for colours", () => {
    expect(findStrayColours("a.tsx", 'href="#root" &#123; id="#main"')).toEqual(
      [],
    );
  });

  it("story 1.4: the tokens file holds the colours", () => {
    const text = readFileSync(join(webRoot, TOKENS_FILE), "utf8");
    expect(findStrayColours(TOKENS_FILE, text).length).toBeGreaterThan(40);
  });
});

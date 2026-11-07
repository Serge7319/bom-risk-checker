const imageHosts = ["mouser.com", "digikey.com", "newark.com", "element14.com", "farnell.com"];

type ComponentKind =
  | "capacitor"
  | "resistor"
  | "inductor"
  | "diode"
  | "transistor"
  | "connector"
  | "sensor"
  | "switch"
  | "ic"
  | "relay"
  | "crystal"
  | "transformer"
  | "generic";

function safePhotoSource(value: unknown): string {
  const source = String(value || "").trim();
  try {
    const url = new URL(source);
    const host = url.hostname.toLowerCase().replace(/\.$/, "");
    const trusted = imageHosts.some((domain) => host === domain || host.endsWith(`.${domain}`));
    const safePath = !url.pathname.split("/").some((part) => part === "." || part === "..");
    if (url.protocol === "https:" && !url.username && !url.password && !url.port && trusted && safePath) {
      return url.toString();
    }
  } catch {
    return "";
  }
  return "";
}

function componentKind(part: Record<string, unknown>): ComponentKind {
  const mpn = String(part.MPN || part.mpn || part.manufacturer_part_number || "").trim();
  const text = [part.Category, part.category, part.Description, part.description, mpn]
    .map((item) => String(item || "").toLowerCase())
    .join(" ");
  const mpnRules: Array<[RegExp, ComponentKind]> = [
    [/^(?:grm|grj|grt|ckg|cga|cc\d{4}|cl\d{2}|c\d{4}[a-z]|t49[1245]|taj[a-z]|tcj[a-z]|293d|eeu|eca|eee|ecj|emk|kgm|kcm|vj\d{4}|mal\d)/i, "capacitor"],
    [/^(?:rc\d{4}|erj-|crcw\d|mcr\d|rmcf|rk73|rt\d{4})/i, "resistor"],
    [/^(?:1n\d{3,}|ss\d{2,}|bav\d{2,}|mbr\d{2,}|pmeg\d+)/i, "diode"],
    [/^(?:irf\w+|ao\d{3,}|bss\d{2,}|fdn\d+|si\d{3,})/i, "transistor"],
    [/^(?:2n\d{3,}|bc\d{2,}|mmbt\d+)/i, "transistor"],
    [/^(?:lqh|lqm|lqg|srr|xal|nr\d{2,})/i, "inductor"],
    [/^(?:stm32|atmega|pic\d|esp32|rp2040|ep[fm]\d|am29|mc68|lm\d|ne\d|sn\d|mcp\d|max\d|tps\d|cd\d{2})/i, "ic"],
    [/^(?:cap|capacitor)(?:[-_]|$)/i, "capacitor"],
    [/^(?:res|resistor)(?:[-_]|$)/i, "resistor"],
    [/^(?:dio|led)(?:[-_]|$)/i, "diode"],
    [/^(?:con|connector)(?:[-_]|$)/i, "connector"],
    [/^(?:ic|mcu)(?:[-_]|$)/i, "ic"],
    [/^(?:osc)(?:[-_]|$)/i, "crystal"],
  ];
  for (const [rule, kind] of mpnRules) {
    if (rule.test(mpn)) return kind;
  }
  if (/capacitor|\bcap\b/.test(text)) return "capacitor";
  if (/resistor|\bres\b/.test(text)) return "resistor";
  if (/inductor|\bcoil\b/.test(text)) return "inductor";
  if (/diode|rectifier|zener|led/.test(text)) return "diode";
  if (/transistor|mosfet|bjt/.test(text)) return "transistor";
  if (/connector|header|terminal/.test(text)) return "connector";
  if (/sensor|thermistor/.test(text)) return "sensor";
  if (/relay/.test(text)) return "relay";
  if (/switch/.test(text)) return "switch";
  if (/crystal|oscillator/.test(text)) return "crystal";
  if (/transformer/.test(text)) return "transformer";
  if (/\bic\b|integrated circuit|microcontroller|amplifier|logic|timer|fpga/.test(text)) return "ic";
  return "generic";
}

function packageStyle(part: Record<string, unknown>): "smd" | "th" {
  const text = [
    part.package,
    part.package_type,
    part.case,
    part.Description,
    part.description,
    part.MPN,
    part.mpn,
  ].map((value) => String(value || "").toLowerCase()).join(" ");
  const explicitThroughHole = [part.through_hole, part.is_through_hole, part.tht]
    .some((value) => value === true || value === 1 || String(value || "").toLowerCase() === "true");
  if (explicitThroughHole || /\b(tht|through[ -]?hole|pth|dip|pdip|to-\d{2,3}|axial|radial|leaded|hc-49)\b/.test(text)) return "th";
  return "smd";
}

const kindColor: Record<ComponentKind, string> = {
  capacitor: "violet",
  resistor: "orange",
  inductor: "teal",
  diode: "rose",
  transistor: "green",
  connector: "cyan",
  sensor: "cyan",
  switch: "amber",
  ic: "blue",
  relay: "slate",
  crystal: "slate",
  transformer: "orange",
  generic: "slate",
};

export function PartThumbnail({ part }: { part: Record<string, unknown> }) {
  const photo = safePhotoSource(
    part.photo_thumbnail || part.Photo || part.image_url || part.photo_url,
  );
  const kind = componentKind(part);
  const localArt = `/component-images/${kind}_${packageStyle(part)}.png`;
  const mpn = String(part.MPN || part.mpn || "component");
  const label = photo
    ? `Product photo for ${mpn}`
    : `Representative ${kind} image; exact part may vary`;

  return (
    <span className={`cv-part-thumb ${kindColor[kind]}`} role="img" aria-label={label} title={label}>
      {/* Supplier photos are HTTPS URLs from the supported distributor allowlist. */}
      {/* eslint-disable-next-line @next/next/no-img-element */}
      <img
        src={photo || localArt}
        alt=""
        loading="lazy"
        decoding="async"
        referrerPolicy="no-referrer"
      />
    </span>
  );
}

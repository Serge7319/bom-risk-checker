"""Declarative component-family attribute profiles for Alternative Finder.

One registry drives supplier normalization keys, datasheet comparison matrices,
engineering scoring, recommendation wording, compact UI, and PDF evidence.
Supplier Direct/Upgrade/Similar labels remain relationship evidence only and
never imply electrical drop-in compatibility.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable, Mapping


COMPARE_EXACT = "exact"
COMPARE_MOUNTING = "mounting"
COMPARE_NOMINAL = "nominal"
COMPARE_LIMIT_GE = "limit_ge"
COMPARE_LIMIT_LE = "limit_le"
COMPARE_TYPE = "type"


@dataclass(frozen=True)
class FieldSpec:
    key: str
    label: str
    compare: str = COMPARE_EXACT
    required: bool = False
    unit: str = ""
    pdf_aliases: tuple[str, ...] = ()
    digikey_params: tuple[str, ...] = ()
    mouser_params: tuple[str, ...] = ()
    value_role: str = "nominal"


@dataclass(frozen=True)
class FamilyProfile:
    id: str
    display_name: str
    markers: tuple[str, ...]
    fields: tuple[FieldSpec, ...]
    omit_common: tuple[str, ...] = ()
    scoring_mode: str = "parametric_matrix"
    requires_pinout_for_dropin: bool = False
    architecture_meaningful: bool = False
    aliases: tuple[str, ...] = ()


COMMON_FIELD_SPECS: tuple[FieldSpec, ...] = (
    FieldSpec(
        "package", "Package", compare=COMPARE_EXACT, required=True,
        pdf_aliases=("package", "case", "footprint"),
        digikey_params=("Package / Case", "Supplier Device Package"),
        mouser_params=("Package / Case", "Package", "Supplier Device Package"),
        value_role="text",
    ),
    FieldSpec(
        "pin_count", "Pin count", compare=COMPARE_EXACT,
        pdf_aliases=("pin count", "number of pins", "number of balls"),
        digikey_params=("Number of Pins", "Number of Balls", "Ball Count"),
        mouser_params=("Number of Pins", "Pin Count", "Number of Balls"),
    ),
    FieldSpec(
        "mounting_style", "Mounting", compare=COMPARE_MOUNTING, required=True,
        pdf_aliases=("mounting", "mounting type", "mounting style"),
        digikey_params=("Mounting Type",),
        mouser_params=("Mounting Style", "Mounting Type"),
        value_role="text",
    ),
    FieldSpec(
        "voltage_range", "Supply voltage", compare=COMPARE_EXACT, unit="V",
        pdf_aliases=("supply voltage", "operating voltage", "voltage - supply"),
        digikey_params=("Voltage - Supply", "Supply Voltage", "Operating Supply Voltage"),
        mouser_params=("Supply Voltage", "Operating Supply Voltage", "Voltage - Supply"),
        value_role="range",
    ),
    FieldSpec(
        "temperature_range", "Temperature range", compare=COMPARE_EXACT, unit="C",
        pdf_aliases=("operating temperature", "temperature range"),
        digikey_params=("Operating Temperature",),
        mouser_params=("Operating Temperature", "Temperature Range"),
        value_role="range",
    ),
    FieldSpec(
        "lifecycle_status", "Lifecycle", compare=COMPARE_EXACT,
        pdf_aliases=("product status", "lifecycle"), value_role="text",
    ),
)


def _f(
    key: str,
    label: str,
    *,
    compare: str = COMPARE_EXACT,
    required: bool = False,
    unit: str = "",
    pdf: tuple[str, ...] = (),
    digikey: tuple[str, ...] = (),
    mouser: tuple[str, ...] = (),
    role: str = "nominal",
) -> FieldSpec:
    return FieldSpec(
        key=key, label=label, compare=compare, required=required, unit=unit,
        pdf_aliases=pdf or (label.casefold(),),
        digikey_params=digikey, mouser_params=mouser, value_role=role,
    )


FAMILY_PROFILES: dict[str, FamilyProfile] = {}


def _register(profile: FamilyProfile) -> FamilyProfile:
    FAMILY_PROFILES[profile.id] = profile
    for alias in profile.aliases:
        FAMILY_PROFILES[alias] = profile
    return profile


_register(FamilyProfile(
    id="Capacitor", display_name="Capacitor",
    markers=("capacitor", "mlcc", "ceramic cap", "tantalum", "electrolytic", "cap "),
    omit_common=("pin_count", "voltage_range"), scoring_mode="parametric_matrix",
    fields=(
        _f("capacitance", "Capacitance", compare=COMPARE_NOMINAL, required=True, unit="F",
           pdf=("capacitance",), digikey=("Capacitance",), mouser=("Capacitance",)),
        _f("tolerance", "Tolerance", required=True, pdf=("tolerance",),
           digikey=("Tolerance",), mouser=("Tolerance",)),
        _f("rated_voltage", "Rated voltage", compare=COMPARE_LIMIT_GE, required=True, unit="V",
           pdf=("rated voltage", "voltage rating"), role="max",
           digikey=("Voltage - Rated", "Voltage Rating"), mouser=("Voltage Rating", "Voltage - Rated")),
        _f("dielectric", "Dielectric", required=True, pdf=("dielectric", "temperature characteristic"),
           digikey=("Temperature Coefficient", "Dielectric"),
           mouser=("Dielectric Characteristic", "Temperature Coefficient")),
        _f("temperature_coefficient", "Temperature characteristic",
           pdf=("temperature characteristic", "temperature coefficient"),
           digikey=("Temperature Coefficient",), mouser=("Temperature Coefficient",)),
        _f("esr", "ESR", compare=COMPARE_LIMIT_LE, unit="Ohm",
           pdf=("esr", "equivalent series resistance"), role="max",
           digikey=("ESR (Equivalent Series Resistance)", "ESR"), mouser=("ESR",)),
        _f("ripple_current", "Ripple current", compare=COMPARE_LIMIT_GE, unit="A",
           pdf=("ripple current",), role="max", digikey=("Ripple Current",), mouser=("Ripple Current",)),
        _f("polarity", "Polarity", compare=COMPARE_TYPE, pdf=("polarity",),
           digikey=("Polarization", "Polarity"), mouser=("Polarity",)),
    ),
))

_register(FamilyProfile(
    id="Resistor", display_name="Resistor",
    markers=("resistor", "thick film", "thin film", "chip resistor"),
    omit_common=("pin_count", "voltage_range"), scoring_mode="parametric_matrix",
    fields=(
        _f("resistance", "Resistance", compare=COMPARE_NOMINAL, required=True, unit="Ohm",
           pdf=("resistance",), digikey=("Resistance",), mouser=("Resistance",)),
        _f("tolerance", "Tolerance", required=True, pdf=("tolerance",),
           digikey=("Tolerance",), mouser=("Tolerance",)),
        _f("power_rating", "Power rating", compare=COMPARE_LIMIT_GE, required=True, unit="W",
           pdf=("power rating", "rated power"), role="max",
           digikey=("Power (Watts)", "Power Rating"), mouser=("Power Rating", "Power (Watts)")),
        _f("rated_voltage", "Voltage rating", compare=COMPARE_LIMIT_GE, unit="V",
           pdf=("voltage rating",), role="max",
           digikey=("Voltage Rating", "Voltage - Rated"), mouser=("Voltage Rating",)),
        _f("temperature_coefficient", "Temperature coefficient",
           pdf=("temperature coefficient", "tcr"),
           digikey=("Temperature Coefficient",), mouser=("Temperature Coefficient",)),
        _f("pulse_capability", "Pulse / surge capability", pdf=("pulse", "surge"), role="text"),
    ),
))

_register(FamilyProfile(
    id="Inductor", display_name="Inductor",
    markers=("inductor", "ferrite", "choke", "bead"),
    omit_common=("pin_count", "voltage_range"), scoring_mode="parametric_matrix",
    fields=(
        _f("inductance", "Inductance", compare=COMPARE_NOMINAL, required=True, unit="H",
           pdf=("inductance",), digikey=("Inductance",), mouser=("Inductance",)),
        _f("tolerance", "Tolerance", pdf=("tolerance",), digikey=("Tolerance",), mouser=("Tolerance",)),
        _f("saturation_current", "Saturation current", compare=COMPARE_LIMIT_GE, required=True, unit="A",
           pdf=("saturation current",), role="max",
           digikey=("Current - Saturation",), mouser=("Saturation Current", "Current - Saturation")),
        _f("rated_current", "Rated current", compare=COMPARE_LIMIT_GE, required=True, unit="A",
           pdf=("rated current", "current rating"), role="max",
           digikey=("Current Rating (Amps)", "Current - Rated", "Current Rating"),
           mouser=("Current Rating", "Rated Current")),
        _f("dcr", "DCR", compare=COMPARE_LIMIT_LE, unit="Ohm", pdf=("dcr", "dc resistance"), role="max",
           digikey=("DC Resistance (DCR)",), mouser=("DC Resistance", "DCR")),
        _f("srf", "SRF", compare=COMPARE_LIMIT_GE, unit="Hz", pdf=("self resonant", "srf"), role="min",
           digikey=("Frequency - Self Resonant", "Self Resonant Frequency"),
           mouser=("Self Resonant Frequency",)),
        _f("shielding", "Shielding", pdf=("shielding",), digikey=("Shielding",), mouser=("Shielding",)),
    ),
))

_register(FamilyProfile(
    id="Diode / protection", display_name="Diode / TVS / LED",
    markers=("tvs", "zener", "schottky", "rectifier", "led ", " light emitting", "diode"),
    omit_common=("voltage_range",), scoring_mode="parametric_matrix",
    fields=(
        _f("device_type", "Diode type / function", compare=COMPARE_TYPE, required=True,
           pdf=("diode type", "type"), digikey=("Diode Type", "Technology"),
           mouser=("Product Type", "Diode Type")),
        _f("polarity", "Polarity", compare=COMPARE_TYPE, pdf=("polarity",),
           digikey=("Polarity",), mouser=("Polarity",)),
        _f("reverse_voltage", "Reverse voltage", compare=COMPARE_LIMIT_GE, required=True, unit="V",
           pdf=("reverse voltage", "vrrm", "breakdown voltage"), role="max",
           digikey=("Voltage - DC Reverse (Vr) (Max)", "Voltage - Reverse Standoff (Typ)",
                    "Voltage - Breakdown (Min)", "Reverse Voltage"),
           mouser=("Reverse Voltage", "Breakdown Voltage", "Working Peak Reverse Voltage")),
        _f("forward_current", "Forward current", compare=COMPARE_LIMIT_GE, required=True, unit="A",
           pdf=("forward current", "average rectified"), role="max",
           digikey=("Current - Average Rectified (Io)", "Current - Peak Pulse (10/1000µs)", "Forward Current"),
           mouser=("Forward Current", "Average Rectified Current")),
        _f("forward_voltage", "Forward voltage", compare=COMPARE_LIMIT_LE, unit="V",
           pdf=("forward voltage", "vf"), role="max",
           digikey=("Voltage - Forward (Vf) (Max) @ If", "Forward Voltage"), mouser=("Forward Voltage",)),
        _f("recovery_time", "Reverse recovery", compare=COMPARE_LIMIT_LE, unit="s",
           pdf=("reverse recovery", "trr"), role="max",
           digikey=("Reverse Recovery Time (trr)", "Recovery Time"), mouser=("Reverse Recovery Time",)),
        _f("power_rating", "Power", compare=COMPARE_LIMIT_GE, unit="W",
           pdf=("power dissipation", "power rating"), role="max",
           digikey=("Power - Peak Pulse", "Power Dissipation", "Power (Watts)"),
           mouser=("Power Dissipation", "Power Rating")),
        _f("capacitance", "Capacitance", compare=COMPARE_LIMIT_LE, unit="F",
           pdf=("capacitance",), role="max",
           digikey=("Capacitance @ Vr, F", "Capacitance"), mouser=("Capacitance",)),
    ),
))

_register(FamilyProfile(
    id="Bipolar transistor", display_name="Bipolar transistor",
    markers=("bjt", "bipolar transistor", "npn", "pnp", "transistor"),
    omit_common=("voltage_range",), scoring_mode="parametric_matrix",
    requires_pinout_for_dropin=True,
    fields=(
        _f("device_type", "Transistor polarity", compare=COMPARE_TYPE, required=True,
           pdf=("transistor type", "polarity", "npn", "pnp"),
           digikey=("Transistor Type", "Technology"), mouser=("Transistor Polarity", "Transistor Type")),
        _f("collector_emitter_voltage", "VCEO", compare=COMPARE_LIMIT_GE, required=True, unit="V",
           pdf=("vceo", "collector-emitter", "v(br)ceo"), role="max",
           digikey=("Voltage - Collector Emitter Breakdown (Max)", "Vce(max)",
                    "Collector Emitter Voltage VCEO Max"),
           mouser=("Collector-Emitter Voltage VCEO Max", "VCEO")),
        _f("collector_base_voltage", "VCBO", compare=COMPARE_LIMIT_GE, unit="V",
           pdf=("vcbo", "collector-base"), role="max",
           digikey=("Voltage - Collector Base (Max)", "VCBO"), mouser=("Collector-Base Voltage VCBO",)),
        _f("collector_current", "IC max", compare=COMPARE_LIMIT_GE, required=True, unit="A",
           pdf=("collector current", "ic (max)"), role="max",
           digikey=("Current - Collector (Ic) (Max)", "Collector Current"),
           mouser=("Collector Current (Continuous)", "Continuous Collector Current")),
        _f("dc_current_gain", "hFE", compare=COMPARE_EXACT, required=True,
           pdf=("hfe", "dc current gain", "current gain"), role="min",
           digikey=("DC Current Gain (hFE) (Min) @ Ic, Vce", "DC Current Gain hFE Max"),
           mouser=("DC Current Gain hFE Max", "hFE")),
        _f("power_dissipation", "Power dissipation", compare=COMPARE_LIMIT_GE, required=True, unit="W",
           pdf=("power dissipation", "pd"), role="max",
           digikey=("Power - Max", "Power Dissipation"), mouser=("Power Dissipation", "Pd - Power Dissipation")),
        _f("transition_frequency", "Transition frequency", compare=COMPARE_LIMIT_GE, unit="Hz",
           pdf=("transition frequency", "ft", "f_t"), role="min",
           digikey=("Frequency - Transition", "Transition Frequency"),
           mouser=("Transition Frequency", "Gain Bandwidth Product fT")),
        _f("vce_saturation", "VCE(sat)", compare=COMPARE_LIMIT_LE, unit="V",
           pdf=("vce(sat)", "collector emitter saturation"), role="max",
           digikey=("Vce Saturation (Max) @ Ib, Ic", "Vce Saturation Max"),
           mouser=("Collector-Emitter Saturation Voltage", "Vce(sat)")),
        _f("collector_cutoff_current", "Leakage", compare=COMPARE_LIMIT_LE, unit="A",
           pdf=("collector cutoff", "leakage", "icbo"), role="max",
           digikey=("Current - Collector Cutoff (Max)",), mouser=("Collector Cutoff Current",)),
        _f("pinout", "Pinout / footprint", compare=COMPARE_EXACT, required=True,
           pdf=("pinout", "pin configuration", "pin assignment"), role="text"),
    ),
))

_register(FamilyProfile(
    id="MOSFET", display_name="MOSFET",
    markers=("mosfet", "n-channel", "p-channel", "hexfet", "power fet"),
    omit_common=("voltage_range",), scoring_mode="parametric_matrix",
    requires_pinout_for_dropin=True,
    fields=(
        _f("device_type", "Channel type", compare=COMPARE_TYPE, required=True,
           pdf=("fet type", "channel", "n-channel", "p-channel"),
           digikey=("FET Type", "Transistor Type", "Technology"),
           mouser=("Transistor Polarity", "Channel Type")),
        _f("drain_source_voltage", "VDS", compare=COMPARE_LIMIT_GE, required=True, unit="V",
           pdf=("vds", "drain-source voltage"), role="max",
           digikey=("Drain to Source Voltage (Vdss)", "Vds - Drain-Source Breakdown Voltage"),
           mouser=("Drain-Source Breakdown Voltage", "Vds")),
        _f("continuous_drain_current", "ID", compare=COMPARE_LIMIT_GE, required=True, unit="A",
           pdf=("drain current", "id (continuous)"), role="max",
           digikey=("Current - Continuous Drain (Id) @ 25°C", "Continuous Drain Current"),
           mouser=("Continuous Drain Current", "Id - Continuous Drain Current")),
        _f("rds_on", "RDS(on)", compare=COMPARE_LIMIT_LE, required=True, unit="Ohm",
           pdf=("rds(on)", "rds on", "drain-source on resistance"), role="max",
           digikey=("Rds On (Max) @ Id, Vgs", "Rds On - Drain-Source Resistance"),
           mouser=("Rds On - Drain-Source Resistance", "Drain-Source Resistance")),
        _f("gate_threshold", "Gate threshold", compare=COMPARE_EXACT, unit="V",
           pdf=("gate threshold", "vgs(th)"),
           digikey=("Vgs(th) (Max) @ Id", "Gate-Source Threshold Voltage"),
           mouser=("Vgs th - Gate-Source Threshold Voltage",)),
        _f("gate_charge", "Gate charge", compare=COMPARE_LIMIT_LE, unit="C",
           pdf=("gate charge", "qg"), role="max",
           digikey=("Gate Charge (Qg) (Max) @ Vgs", "Total Gate Charge"),
           mouser=("Total Gate Charge", "Qg - Gate Charge")),
        _f("power_dissipation", "Power", compare=COMPARE_LIMIT_GE, unit="W",
           pdf=("power dissipation",), role="max",
           digikey=("Power Dissipation (Max)", "Power - Max"), mouser=("Power Dissipation",)),
        _f("thermal_resistance", "Thermal resistance", compare=COMPARE_LIMIT_LE,
           pdf=("thermal resistance", "rθja", "rth"), role="max",
           digikey=("Thermal Resistance",), mouser=("Thermal Resistance",)),
        _f("pinout", "Pinout / footprint", compare=COMPARE_EXACT, required=True,
           pdf=("pinout", "pin configuration"), role="text"),
    ),
))

_register(FamilyProfile(
    id="Regulator", display_name="Regulator / power IC",
    markers=("regulator", "ldo", "buck", "boost", "switching regulator", "voltage regulator"),
    scoring_mode="parametric_matrix", architecture_meaningful=True,
    fields=(
        _f("architecture", "Topology / function", compare=COMPARE_TYPE, required=True,
           pdf=("regulator type", "topology", "function"),
           digikey=("Topology", "Function"), mouser=("Product Type", "Type")),
        _f("voltage_range", "Input voltage range", compare=COMPARE_EXACT, required=True, unit="V",
           pdf=("input voltage", "vin"), role="range",
           digikey=("Voltage - Input (Min)", "Voltage - Input (Max)", "Voltage - Input"),
           mouser=("Input Voltage", "Input Voltage MAX")),
        _f("output_voltage", "Output voltage", compare=COMPARE_NOMINAL, required=True, unit="V",
           pdf=("output voltage", "vout"),
           digikey=("Voltage - Output (Min/Fixed)", "Voltage - Output (Max)", "Output Voltage"),
           mouser=("Output Voltage",)),
        _f("rated_current", "Output current", compare=COMPARE_LIMIT_GE, required=True, unit="A",
           pdf=("output current", "iout"), role="max",
           digikey=("Current - Output", "Output Current"), mouser=("Output Current",)),
        _f("dropout_voltage", "Dropout voltage", compare=COMPARE_LIMIT_LE, unit="V",
           pdf=("dropout",), role="max",
           digikey=("Voltage Dropout (Max)", "Dropout Voltage"), mouser=("Dropout Voltage",)),
        _f("switching_frequency", "Switching frequency", compare=COMPARE_EXACT, unit="Hz",
           pdf=("switching frequency", "fsw"),
           digikey=("Frequency - Switching",), mouser=("Switching Frequency",)),
        _f("pinout", "Enable / feedback / pin compatibility", compare=COMPARE_EXACT, required=True,
           pdf=("pinout", "pin configuration", "enable", "feedback"), role="text"),
        _f("power_dissipation", "Thermal limits", compare=COMPARE_LIMIT_GE, unit="W",
           pdf=("power dissipation", "thermal"), role="max",
           digikey=("Power Dissipation",), mouser=("Power Dissipation",)),
    ),
))

_register(FamilyProfile(
    id="Operational amplifier", display_name="Operational amplifier",
    markers=("operational amplifier", "op amp", "op-amp", "opamp"),
    scoring_mode="ic_weighted", architecture_meaningful=True,
    fields=(
        _f("architecture", "Function / category", compare=COMPARE_TYPE, required=True,
           pdf=("amplifier type", "function"), digikey=("Amplifier Type",), mouser=("Amplifier Type",)),
        _f("channel_count", "Channels", compare=COMPARE_EXACT, required=True,
           pdf=("channels", "number of circuits"),
           digikey=("Number of Circuits",), mouser=("Number of Channels",)),
        _f("voltage_range", "Supply voltage", compare=COMPARE_EXACT, required=True, unit="V",
           pdf=("supply voltage",), role="range",
           digikey=("Voltage - Supply Span (Min)", "Voltage - Supply Span (Max)", "Voltage - Supply"),
           mouser=("Supply Voltage",)),
        _f("bandwidth_mhz", "Bandwidth", compare=COMPARE_LIMIT_GE, unit="Hz",
           pdf=("bandwidth", "gain bandwidth"), role="min",
           digikey=("Gain Bandwidth Product", "Bandwidth"), mouser=("Gain Bandwidth Product",)),
        _f("slew_rate_v_us", "Slew rate", compare=COMPARE_LIMIT_GE, pdf=("slew rate",), role="min",
           digikey=("Slew Rate",), mouser=("Slew Rate",)),
        _f("input_offset_mv", "Input offset", compare=COMPARE_LIMIT_LE, unit="V",
           pdf=("input offset",), role="max",
           digikey=("Voltage - Input Offset",), mouser=("Input Offset Voltage",)),
        _f("input_bias_na", "Input bias", compare=COMPARE_LIMIT_LE, unit="A",
           pdf=("input bias",), role="max",
           digikey=("Current - Input Bias",), mouser=("Input Bias Current",)),
        _f("pinout", "Pinout", compare=COMPARE_EXACT, required=True,
           pdf=("pinout", "pin configuration"), role="text"),
    ),
))

_register(FamilyProfile(
    id="Logic / interface IC", display_name="Analog / logic / interface IC",
    markers=("comparator", "shift register", "inverter", "logic gate", "buffer",
             "transceiver", "interface", "level shifter", "uart", "i2c", "spi ",
             "analog switch", "multiplexer", "mux "),
    scoring_mode="ic_weighted", architecture_meaningful=True,
    fields=(
        _f("architecture", "Function / category", compare=COMPARE_TYPE, required=True,
           pdf=("logic type", "function", "category"),
           digikey=("Logic Type", "Function"), mouser=("Product Type", "Logic Type")),
        _f("voltage_range", "Supply voltage", compare=COMPARE_EXACT, required=True, unit="V",
           pdf=("supply voltage",), role="range",
           digikey=("Voltage - Supply",), mouser=("Supply Voltage",)),
        _f("interface", "I/O / interface type", compare=COMPARE_TYPE,
           pdf=("interface", "protocol", "i/o"),
           digikey=("Interface", "Protocol"), mouser=("Interface Type",)),
        _f("frequency_mhz", "Key performance limit", compare=COMPARE_LIMIT_GE, unit="Hz",
           pdf=("frequency", "data rate", "propagation"), role="min",
           digikey=("Data Rate", "Frequency", "Max Propagation Delay"), mouser=("Data Rate", "Frequency")),
        _f("pinout", "Pinout", compare=COMPARE_EXACT, required=True,
           pdf=("pinout", "pin configuration"), role="text"),
    ),
))

_register(FamilyProfile(
    id="MCU / processor", display_name="MCU / processor",
    markers=("microcontroller", "mcu", "microprocessor", "processor", "arm cortex", "stm32", "avr "),
    scoring_mode="resource_device", requires_pinout_for_dropin=True, architecture_meaningful=True,
    aliases=("Logic / processor",),
    fields=(
        _f("architecture", "Device family / architecture", compare=COMPARE_TYPE, required=True,
           pdf=("core", "architecture", "family"),
           digikey=("Core Processor", "Series"), mouser=("Core", "Product Type")),
        _f("memory_size", "Memory resources", compare=COMPARE_LIMIT_GE,
           pdf=("flash", "ram", "memory"), role="min",
           digikey=("Program Memory Size", "RAM Size"), mouser=("Program Memory Size", "RAM Size")),
        _f("io_count", "I/O count", compare=COMPARE_LIMIT_GE,
           pdf=("number of i/o", "i/o"), role="min",
           digikey=("Number of I/O",), mouser=("Number of I/Os",)),
        _f("voltage_range", "Voltage domains", compare=COMPARE_EXACT, required=True, unit="V",
           pdf=("voltage - supply", "core voltage"), role="range",
           digikey=("Voltage - Supply (Vcc/Vdd)",), mouser=("Supply Voltage",)),
        _f("frequency_mhz", "Clock / speed", compare=COMPARE_LIMIT_GE, unit="Hz",
           pdf=("speed", "clock", "frequency"), role="min",
           digikey=("Speed", "Maximum Clock Frequency"), mouser=("Maximum Clock Frequency",)),
        _f("peripherals", "Peripheral capabilities", compare=COMPARE_EXACT,
           pdf=("peripherals", "connectivity"),
           digikey=("Peripherals", "Connectivity"), mouser=("Peripherals",)),
        _f("pinout", "Pinout / configuration compatibility", compare=COMPARE_EXACT, required=True,
           pdf=("pinout", "pin configuration"), role="text"),
    ),
))

_register(FamilyProfile(
    id="FPGA / CPLD", display_name="FPGA / CPLD / PAL",
    markers=("fpga", "cpld", "pal ", "gal ", "pld", "artix", "kintex", "virtex", "cyclone", "max ii"),
    scoring_mode="resource_device", requires_pinout_for_dropin=True, architecture_meaningful=True,
    fields=(
        _f("architecture", "Device family", compare=COMPARE_TYPE, required=True,
           pdf=("family", "series", "device"), digikey=("Series", "Family"), mouser=("Product Type", "Series")),
        _f("logic_resources", "Logic resources", compare=COMPARE_LIMIT_GE, required=True,
           pdf=("logic elements", "lut", "macrocells", "system gates"), role="min",
           digikey=("Number of Logic Elements/Cells", "Number of LABs/CLBs", "Number of Macrocells"),
           mouser=("Number of Logic Elements", "Number of Macrocells")),
        _f("memory_size", "Memory resources", compare=COMPARE_LIMIT_GE,
           pdf=("total ram", "block ram"), role="min",
           digikey=("Total RAM Bits",), mouser=("Embedded Memory",)),
        _f("io_count", "I/O count", compare=COMPARE_LIMIT_GE, required=True,
           pdf=("number of i/o",), role="min", digikey=("Number of I/O",), mouser=("Number of I/Os",)),
        _f("voltage_range", "Voltage domains", compare=COMPARE_EXACT, required=True, unit="V",
           pdf=("voltage - supply",), role="range",
           digikey=("Voltage - Supply",), mouser=("Supply Voltage",)),
        _f("pinout", "Pinout / configuration compatibility", compare=COMPARE_EXACT, required=True,
           pdf=("pinout", "configuration", "programming"), role="text"),
    ),
))

_register(FamilyProfile(
    id="Connector / electromechanical", display_name="Connector",
    markers=("connector", "header", "receptacle", "plug ", "socket"),
    omit_common=("pin_count", "voltage_range"), scoring_mode="parametric_matrix",
    fields=(
        _f("positions", "Positions", compare=COMPARE_EXACT, required=True,
           pdf=("positions", "number of positions", "number of contacts"),
           digikey=("Number of Positions",), mouser=("Number of Positions",)),
        _f("pitch", "Pitch", compare=COMPARE_NOMINAL, required=True, unit="m",
           pdf=("pitch",), digikey=("Pitch - Mating", "Pitch"), mouser=("Pitch",)),
        _f("rated_current", "Current rating", compare=COMPARE_LIMIT_GE, unit="A",
           pdf=("current rating",), role="max",
           digikey=("Current Rating (Amps)",), mouser=("Current Rating",)),
        _f("rated_voltage", "Voltage rating", compare=COMPARE_LIMIT_GE, unit="V",
           pdf=("voltage rating",), role="max",
           digikey=("Voltage Rating",), mouser=("Voltage Rating",)),
        _f("mating_style", "Mating / interface", compare=COMPARE_TYPE, required=True,
           pdf=("connector type", "gender", "mating"),
           digikey=("Connector Type", "Gender"), mouser=("Product Type", "Gender")),
    ),
))

_register(FamilyProfile(
    id="Relay", display_name="Relay", markers=("relay",),
    omit_common=("pin_count", "voltage_range"), scoring_mode="parametric_matrix",
    fields=(
        _f("device_type", "Relay type / contact form", compare=COMPARE_TYPE, required=True,
           pdf=("contact form", "relay type"),
           digikey=("Contact Form", "Relay Type"), mouser=("Contact Form", "Relay Type")),
        _f("coil_voltage", "Coil voltage", compare=COMPARE_NOMINAL, required=True, unit="V",
           pdf=("coil voltage",), digikey=("Coil Voltage",), mouser=("Coil Voltage",)),
        _f("rated_current", "Contact current", compare=COMPARE_LIMIT_GE, required=True, unit="A",
           pdf=("contact rating", "switching current"), role="max",
           digikey=("Contact Rating (Current)",), mouser=("Contact Current Rating",)),
        _f("rated_voltage", "Contact voltage", compare=COMPARE_LIMIT_GE, unit="V",
           pdf=("contact voltage",), role="max",
           digikey=("Switching Voltage",), mouser=("Contact Voltage",)),
    ),
))

_register(FamilyProfile(
    id="Switch", display_name="Switch",
    markers=("switch", "tactile", "pushbutton", "dip switch"),
    omit_common=("pin_count", "voltage_range"), scoring_mode="parametric_matrix",
    fields=(
        _f("device_type", "Switch type", compare=COMPARE_TYPE, required=True,
           pdf=("switch type", "circuit"),
           digikey=("Circuit", "Switch Type"), mouser=("Switch Type", "Circuit")),
        _f("rated_current", "Current rating", compare=COMPARE_LIMIT_GE, unit="A",
           pdf=("current rating",), role="max",
           digikey=("Current Rating (Amps)",), mouser=("Current Rating",)),
        _f("rated_voltage", "Voltage rating", compare=COMPARE_LIMIT_GE, unit="V",
           pdf=("voltage rating",), role="max",
           digikey=("Voltage Rating - AC", "Voltage Rating - DC"), mouser=("Voltage Rating",)),
    ),
))

_register(FamilyProfile(
    id="Oscillator / crystal", display_name="Crystal / oscillator",
    markers=("oscillator", "crystal", "xtal", "mems oscillator"),
    omit_common=("pin_count", "voltage_range"), scoring_mode="parametric_matrix",
    fields=(
        _f("frequency_mhz", "Frequency", compare=COMPARE_NOMINAL, required=True, unit="Hz",
           pdf=("frequency",), digikey=("Frequency",), mouser=("Frequency",)),
        _f("frequency_tolerance", "Frequency tolerance", required=True,
           pdf=("frequency tolerance", "stability"),
           digikey=("Frequency Stability", "Frequency Tolerance"), mouser=("Frequency Stability",)),
        _f("load_capacitance", "Load capacitance", compare=COMPARE_NOMINAL, unit="F",
           pdf=("load capacitance",), digikey=("Load Capacitance",), mouser=("Load Capacitance",)),
        _f("voltage_range", "Supply voltage", compare=COMPARE_EXACT, unit="V",
           pdf=("voltage - supply",), role="range",
           digikey=("Voltage - Supply",), mouser=("Supply Voltage",)),
    ),
))

_register(FamilyProfile(
    id="Sensor", display_name="Sensor",
    markers=("sensor", "accelerometer", "gyroscope", "magnetometer", "temperature sensor", "humidity"),
    omit_common=("pin_count",), scoring_mode="parametric_matrix",
    fields=(
        _f("device_type", "Sensor type", compare=COMPARE_TYPE, required=True,
           pdf=("sensor type",), digikey=("Sensor Type",), mouser=("Product Type",)),
        _f("measurement_range", "Measurement range", compare=COMPARE_EXACT, required=True,
           pdf=("measurement range", "range"),
           digikey=("Measuring Range", "Acceleration Range"), mouser=("Measuring Range",)),
        _f("accuracy", "Accuracy", compare=COMPARE_EXACT, pdf=("accuracy", "sensitivity"),
           digikey=("Accuracy", "Sensitivity"), mouser=("Accuracy",)),
        _f("interface", "Interface", compare=COMPARE_TYPE, required=True,
           pdf=("interface", "output type"),
           digikey=("Output Type", "Interface"), mouser=("Interface", "Output Type")),
        _f("voltage_range", "Supply voltage", compare=COMPARE_EXACT, required=True, unit="V",
           pdf=("supply voltage",), role="range",
           digikey=("Voltage - Supply",), mouser=("Supply Voltage",)),
    ),
))

_register(FamilyProfile(
    id="Transformer", display_name="Transformer", markers=("transform",),
    omit_common=("pin_count", "voltage_range"), scoring_mode="parametric_matrix",
    fields=(
        _f("turns_ratio", "Turns ratio", compare=COMPARE_EXACT, required=True,
           pdf=("turns ratio",), digikey=("Turns Ratio - Primary:Secondary",), mouser=("Turns Ratio",)),
        _f("isolation_voltage", "Isolation voltage", compare=COMPARE_LIMIT_GE, unit="V",
           pdf=("isolation voltage",), role="max",
           digikey=("Voltage - Isolation",), mouser=("Isolation Voltage",)),
        _f("power_rating", "Power rating", compare=COMPARE_LIMIT_GE, unit="W",
           pdf=("power rating",), role="max", digikey=("Power Rating",), mouser=("Power Rating",)),
        _f("inductance", "Inductance", compare=COMPARE_NOMINAL, unit="H",
           pdf=("inductance",), digikey=("Inductance",), mouser=("Inductance",)),
    ),
))

_register(FamilyProfile(
    id="General electronic component", display_name="General electronic component",
    markers=(), fields=(), scoring_mode="parametric_matrix",
))

_INFERENCE_ORDER: tuple[str, ...] = (
    "FPGA / CPLD", "MCU / processor", "Operational amplifier", "Logic / interface IC",
    "Regulator", "MOSFET", "Bipolar transistor", "Diode / protection", "Capacitor",
    "Resistor", "Inductor", "Transformer", "Oscillator / crystal", "Sensor", "Relay",
    "Switch", "Connector / electromechanical",
)


def get_family_profile(family: str | None) -> FamilyProfile:
    name = str(family or "").strip()
    if name in FAMILY_PROFILES:
        return FAMILY_PROFILES[name]
    if name == "Transistor / MOSFET":
        return FAMILY_PROFILES["Bipolar transistor"]
    if name == "Logic / processor":
        return FAMILY_PROFILES["MCU / processor"]
    return FAMILY_PROFILES["General electronic component"]


def infer_family_id(part: Mapping) -> str:
    text = " ".join(
        str(part.get(key) or "")
        for key in (
            "description", "architecture", "manufacturer_part_number",
            "device_type", "Category", "category",
        )
    ).casefold()
    for family_id in _INFERENCE_ORDER:
        profile = FAMILY_PROFILES[family_id]
        for marker in profile.markers:
            if marker and marker in text:
                return family_id
    return "General electronic component"


def comparison_fields(profile: FamilyProfile) -> list[FieldSpec]:
    fields: list[FieldSpec] = []
    for spec in COMMON_FIELD_SPECS:
        if spec.key in profile.omit_common:
            continue
        fields.append(spec)
    seen = {spec.key for spec in fields}
    for spec in profile.fields:
        if spec.key in seen:
            fields = [item for item in fields if item.key != spec.key]
            seen.discard(spec.key)
        fields.append(spec)
        seen.add(spec.key)
    return fields


def all_parametric_keys(include_common: bool = True) -> tuple[str, ...]:
    keys: list[str] = []
    seen: set[str] = set()
    unique_profiles = {id(p): p for p in FAMILY_PROFILES.values()}.values()
    sources: list[FieldSpec] = list(COMMON_FIELD_SPECS) if include_common else []
    for profile in unique_profiles:
        sources.extend(profile.fields)
    for spec in sources:
        if spec.key not in seen:
            seen.add(spec.key)
            keys.append(spec.key)
    return tuple(keys)


def digikey_parametric_map() -> dict[str, list[str]]:
    mapping: dict[str, list[str]] = {}
    for profile in {id(p): p for p in FAMILY_PROFILES.values()}.values():
        for spec in (*COMMON_FIELD_SPECS, *profile.fields):
            if not spec.digikey_params:
                continue
            existing = mapping.setdefault(spec.key, [])
            for name in spec.digikey_params:
                if name not in existing:
                    existing.append(name)
    return mapping


def mouser_parametric_map() -> dict[str, list[str]]:
    mapping: dict[str, list[str]] = {}
    for profile in {id(p): p for p in FAMILY_PROFILES.values()}.values():
        for spec in (*COMMON_FIELD_SPECS, *profile.fields):
            if not spec.mouser_params:
                continue
            existing = mapping.setdefault(spec.key, [])
            for name in spec.mouser_params:
                if name not in existing:
                    existing.append(name)
    return mapping


def pdf_label_aliases() -> dict[str, tuple[str, ...]]:
    aliases: dict[str, tuple[str, ...]] = {}
    for profile in {id(p): p for p in FAMILY_PROFILES.values()}.values():
        for spec in (*COMMON_FIELD_SPECS, *profile.fields):
            aliases[spec.label] = spec.pdf_aliases or (spec.label.casefold(),)
    return aliases


def legacy_family_fields() -> dict[str, tuple[tuple[str, str], ...]]:
    result: dict[str, tuple[tuple[str, str], ...]] = {}
    for family_id in _INFERENCE_ORDER:
        profile = FAMILY_PROFILES[family_id]
        result[profile.id] = tuple((spec.label, spec.key) for spec in profile.fields)
    result["Transistor / MOSFET"] = result["Bipolar transistor"]
    result["Logic / processor"] = result["MCU / processor"]
    return result


PASSIVE_FAMILY_IDS = frozenset({"Capacitor", "Resistor", "Inductor"})
DISCRETE_PARAMETRIC_FAMILY_IDS = frozenset({
    "Capacitor", "Resistor", "Inductor", "Transformer", "Diode / protection",
    "Bipolar transistor", "MOSFET", "Relay", "Switch",
    "Connector / electromechanical", "Oscillator / crystal", "Sensor", "Regulator",
})

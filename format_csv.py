import json
import pandas as pd

# ==========================================================
# CONFIG
# ==========================================================

INPUT_JSON = "Prob156_review2015_fancytimer_ref_output.json"

OUTPUT_NODE = "nodes.csv"
OUTPUT_EDGE = "edges.csv"

# ==========================================================
# Read JSON
# ==========================================================

with open(INPUT_JSON, "r") as f:
    design = json.load(f)

module_name = list(design["modules"].keys())[0]
module = design["modules"][module_name]

# ==========================================================
# Containers
# ==========================================================

nodes = []
edges = []

node_set = set()

bit_to_net = {}

# ==========================================================
# Helper
# ==========================================================

def add_node(node_id, node_type, label=None):

    if node_id in node_set:
        return

    node_set.add(node_id)

    nodes.append({
        "id": node_id,
        "type": node_type,
        "label": label if label else node_id
    })


def gate_type(cell_type):

    t = cell_type.upper()

    if "DFF" in t:
        return "FlipFlop"

    if "MUX" in t:
        return "MUX"

    if "ANDNOT" in t:
        return "ANDNOT"

    if "ORNOT" in t:
        return "ORNOT"

    if "XNOR" in t:
        return "XNOR"

    if "XOR" in t:
        return "XOR"

    if "NAND" in t:
        return "NAND"

    if "NOR" in t:
        return "NOR"

    if "AND" in t:
        return "AND"

    if "OR" in t:
        return "OR"

    if "NOT" in t:
        return "NOT"

    return "Gate"


# ==========================================================
# Build bit -> net mapping
# ==========================================================

for net_name, net in module["netnames"].items():

    bits = net["bits"]

    if len(bits) == 1:

        bit = bits[0]

        bit_to_net[bit] = net_name

    else:

        for idx, bit in enumerate(bits):

            bit_to_net[bit] = f"{net_name}[{idx}]"

# ==========================================================
# Create Wire nodes
# ==========================================================

for bit, name in bit_to_net.items():

    add_node(name, "Wire", name)

# ==========================================================
# Ports
# ==========================================================

for port_name, port in module["ports"].items():

    direction = port["direction"]

    if direction == "input":
        add_node(port_name, "Input", port_name)
    else:
        add_node(port_name, "Output", port_name)

    for bit in port["bits"]:

        if bit not in bit_to_net:
            continue

        net_name = bit_to_net[bit]

        if direction == "input":

            edges.append({
                "source": port_name,
                "target": net_name
            })

        else:

            edges.append({
                "source": net_name,
                "target": port_name
            })

# ==========================================================
# Cells
# ==========================================================

OUTPUT_PORTS = {"Y", "Q"}

for cell_name, cell in module["cells"].items():

    ctype = gate_type(cell["type"])

    add_node(cell_name, ctype, cell["type"])

    for port, bits in cell["connections"].items():

        if not isinstance(bits, list):
            bits = [bits]

        for bit in bits:

            if bit not in bit_to_net:
                continue

            net_name = bit_to_net[bit]

            # output pin
            if port in OUTPUT_PORTS:

                edges.append({
                    "source": cell_name,
                    "target": net_name
                })

            # input pin
            else:

                edges.append({
                    "source": net_name,
                    "target": cell_name
                })

# ==========================================================
# Remove duplicate edges
# ==========================================================

edge_df = pd.DataFrame(edges)

edge_df = edge_df.drop_duplicates()

node_df = pd.DataFrame(nodes)

# ==========================================================
# Save
# ==========================================================

node_df.to_csv(OUTPUT_NODE, index=False)

edge_df.to_csv(OUTPUT_EDGE, index=False)

print("=" * 60)
print("Module :", module_name)
print("Nodes  :", len(node_df))
print("Edges  :", len(edge_df))
print("Saved:")
print("  ", OUTPUT_NODE)
print("  ", OUTPUT_EDGE)
print("=" * 60)
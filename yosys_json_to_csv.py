import json
import csv
import sys

def load_module(json_path, module_name=None):
    """Doc file JSON Yosys va tra ve (ten_module, du_lieu_module)."""
    with open(json_path) as f:
        data = json.load(f)
    modules = data["modules"]
    if module_name is None:
        module_name = next(iter(modules))
    return module_name, modules[module_name]


def bit_node_id(port_name, bit_index, total_bits):
    """Sinh id cho 1 bit cua 1 port: port neu 1 bit, port[i] neu nhieu bit."""
    return port_name if total_bits == 1 else f"{port_name}[{bit_index}]"


def convert(mod):
    """
    Chuyen du lieu 1 module Yosys JSON thanh (nodes, edges).
      nodes: list[(id, type, label)]
      edges: list[(source, target)]
    """
    nodes = []
    node_ids_seen = set()
    bit_driver = {}          # bit_id (int) -> node_id lai bit do
    edges = []

    def add_node(nid, ntype, label):
        if nid not in node_ids_seen:
            node_ids_seen.add(nid)
            nodes.append((nid, ntype, label))

    # --- Buoc 1: node cho port Input/Output cua module ---
    ports = mod.get("ports", {})
    for pname, pinfo in ports.items():
        direction = pinfo["direction"]
        bits = pinfo["bits"]
        ntype = "Input" if direction == "input" else "Output"
        for i, b in enumerate(bits):
            nid = bit_node_id(pname, i, len(bits))
            add_node(nid, ntype, nid)
            if direction == "input":
                bit_driver[b] = nid  # input port la nguon (driver) cua bit nay

    # --- Buoc 2 + 3: node cho tung cell, ghi nhan driver cho bit ngo ra ---
    cells = mod.get("cells", {})

    def first_output_bit(cinfo):
        """Dung de sap xep cell theo thu tu xuat hien gan dung (bit ngo ra nho nhat)."""
        pd = cinfo["port_directions"]
        conns = cinfo["connections"]
        for p, d in pd.items():
            if d == "output" and conns.get(p):
                return conns[p][0]
        return float("inf")

    cell_items = sorted(cells.items(), key=lambda kv: first_output_bit(kv[1]))

    cell_node_id = {}
    for cname, cinfo in cell_items:
        raw_type = cinfo["type"]
        base_type = raw_type.strip("$").strip("_")
        pd = cinfo["port_directions"]
        n_in = sum(1 for d in pd.values() if d == "input")
        prefix = f"{base_type}{n_in}"
        nid = f"{prefix}_{len(nodes) + 1}"
        cell_node_id[cname] = nid
        add_node(nid, base_type, nid)

        conns = cinfo["connections"]
        for p, d in pd.items():
            if d == "output":
                for b in conns[p]:
                    bit_driver[b] = nid

    # --- Buoc 4: canh tu driver -> cell dang tieu thu bit do ---
    for cname, cinfo in cell_items:
        nid = cell_node_id[cname]
        pd = cinfo["port_directions"]
        conns = cinfo["connections"]
        for p, d in pd.items():
            if d == "input":
                for b in conns[p]:
                    drv = bit_driver.get(b)
                    if drv is None:
                        # bit khong co driver ro rang -> coi la hang so / khong noi
                        drv = f"CONST_{b}"
                        add_node(drv, "Const", str(b))
                        bit_driver[b] = drv
                    if drv != nid:
                        edges.append((drv, nid))

    # canh tu driver noi bo -> node Output cua module
    for pname, pinfo in ports.items():
        if pinfo["direction"] != "output":
            continue
        bits = pinfo["bits"]
        for i, b in enumerate(bits):
            nid = bit_node_id(pname, i, len(bits))
            drv = bit_driver.get(b)
            if drv is not None and drv != nid:
                edges.append((drv, nid))

    # loai trung canh, giu thu tu xuat hien
    seen = set()
    uniq_edges = []
    for e in edges:
        if e not in seen:
            seen.add(e)
            uniq_edges.append(e)

    return nodes, uniq_edges


def write_csv(nodes, edges, nodes_path, edges_path):
    with open(nodes_path, "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["id", "type", "label"])
        w.writerows(nodes)

    with open(edges_path, "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["source", "target"])
        w.writerows(edges)


def main():
    if len(sys.argv) < 4:
        print(f"Cach dung: python3 {sys.argv[0]} input.json nodes.csv edges.csv")
        sys.exit(1)

    json_path, nodes_path, edges_path = sys.argv[1:4]
    module_name, mod = load_module(json_path)
    nodes, edges = convert(mod)
    write_csv(nodes, edges, nodes_path, edges_path)

    print(f"Module: {module_name}")
    print(f"Nodes : {len(nodes)} -> {nodes_path}")
    print(f"Edges : {len(edges)} -> {edges_path}")


if __name__ == "__main__":
    main()
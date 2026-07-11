import json
import csv
import re
import sys

# netname nao la "rac" sinh tu dong boi cac pass toi uu (khong mang nghia)
JUNK_NETNAME_PATTERNS = [
    r"^\$abc\$\d+\$new_n",
    r"^\$abc\$\d+\$auto\$opt_dff",
    r"^\$abc\$\d+\$auto\$simplemap",
]


def is_junk_netname(name):
    return any(re.match(p, name) for p in JUNK_NETNAME_PATTERNS)


def clean_name(name):
    # "$0\\scount[3:0]" -> "scount_next" ; "$auto$alumacc...94.Y" -> giu nguyen de truy vet
    if name.startswith("$0\\"):
        base = name[3:].split("[")[0]
        return f"{base}_next"
    return name


def load(json_path, module_name=None):
    with open(json_path) as f:
        data = json.load(f)
    modules = data["modules"]
    if module_name is None:
        module_name = next(iter(modules))
    return module_name, modules[module_name]


def bit_node_id(port_name, i, total):
    return port_name if total == 1 else f"{port_name}[{i}]"


def build_base_graph(mod):
    """Giong ban truoc: sinh node (Input/Output/cell) + bit_driver + edges.
    Edges gio la (source, target, target_port) de giu dung chan ket noi
    (A/B/S cho gate, C/D/E/R cho flip-flop) - bat buoc phai co de sinh
    lai Verilog dung chuc nang, vi nhieu port khong doi xung (MUX, DFF,
    ANDNOT, ORNOT)."""
    nodes = {}
    order = []
    bit_driver = {}
    cell_qbits = {}

    def add_node(nid, ntype, label):
        if nid not in nodes:
            nodes[nid] = [ntype, label]
            order.append(nid)

    ports = mod.get("ports", {})
    for pname, pinfo in ports.items():
        direction = pinfo["direction"]
        bits = pinfo["bits"]
        ntype = "Input" if direction == "input" else "Output"
        for i, b in enumerate(bits):
            nid = bit_node_id(pname, i, len(bits))
            add_node(nid, ntype, nid)
            if direction == "input":
                bit_driver[b] = nid

    cells = mod.get("cells", {})

    def first_output_bit(cinfo):
        pd = cinfo["port_directions"]
        conns = cinfo["connections"]
        for p, d in pd.items():
            if d == "output" and conns.get(p):
                return conns[p][0]
        return float("inf")

    cell_items = sorted(cells.items(), key=lambda kv: first_output_bit(kv[1]))

    cell_node_id = {}
    cell_type_by_nid = {}
    for cname, cinfo in cell_items:
        base_type = cinfo["type"].strip("$").strip("_")
        pd = cinfo["port_directions"]
        n_in = sum(1 for d in pd.values() if d == "input")
        prefix = f"{base_type}{n_in}"
        nid = f"{prefix}_{len(order) + 1}"
        cell_node_id[cname] = nid
        cell_type_by_nid[nid] = base_type
        add_node(nid, base_type, nid)

        conns = cinfo["connections"]
        for p, d in pd.items():
            if d == "output":
                cell_qbits.setdefault(nid, []).extend(conns[p])
                for b in conns[p]:
                    bit_driver[b] = nid

    edges = []  # (source, target, target_port)
    for cname, cinfo in cell_items:
        nid = cell_node_id[cname]
        pd = cinfo["port_directions"]
        conns = cinfo["connections"]
        for p, d in pd.items():
            if d == "input":
                for b in conns[p]:
                    drv = bit_driver.get(b)
                    if drv is None:
                        drv = f"CONST_{b}"
                        add_node(drv, "Const", str(b))
                        bit_driver[b] = drv
                    if drv != nid:
                        edges.append((drv, nid, p))

    for pname, pinfo in ports.items():
        if pinfo["direction"] != "output":
            continue
        bits = pinfo["bits"]
        for i, b in enumerate(bits):
            nid = bit_node_id(pname, i, len(bits))
            drv = bit_driver.get(b)
            if drv is not None and drv != nid:
                edges.append((drv, nid, ""))  # port module khong co "chan" con

    seen, uniq_edges = set(), []
    for e in edges:
        if e not in seen:
            seen.add(e)
            uniq_edges.append(e)

    return nodes, order, uniq_edges, bit_driver, cell_qbits, cell_type_by_nid


def apply_semantics(mod, nodes, bit_driver, cell_qbits, cell_type_by_nid):
    """
    Doi chieu netnames voi bit Q / bit D de gan semantic_group + role.
    Chi gan khi trung khop CHINH XAC tap bit -> khong doan.
    FSM encoding (enum_value_*) duoc gop thang vao cot state_encoding
    cua CHINH cac node flip-flop thuoc thanh ghi do (khong tach file rieng).
    """
    semantic = {nid: {"semantic_group": "", "role": "", "state_encoding": ""}
                for nid in nodes}

    netnames = mod.get("netnames", {})
    qset_by_nid = {nid: set(bits) for nid, bits in cell_qbits.items()}

    # gom truoc: ten_netname -> chuoi encoding "0000=S;0001=S1;..."
    enum_str_by_netname = {}
    for nname, ninfo in netnames.items():
        attrs = ninfo.get("attributes", {})
        enum_keys = sorted(k for k in attrs if k.startswith("enum_value_"))
        if enum_keys:
            pairs = [f"{k.replace('enum_value_', '')}={attrs[k].lstrip(chr(92))}"
                     for k in enum_keys]
            enum_str_by_netname[nname] = ";".join(pairs)

    for nname, ninfo in netnames.items():
        if is_junk_netname(nname):
            continue
        bits = ninfo.get("bits", [])
        if not bits:
            continue
        bitset = set(bits)
        label = clean_name(nname)
        enc_str = enum_str_by_netname.get(nname, "")

        # 1) netname trung voi TAP HOP Q-bit cua cac node co output roi vao bitset nay
        matched = [nid for nid, qs in qset_by_nid.items() if qs & bitset]
        union_q = set()
        for nid in matched:
            union_q |= qset_by_nid[nid]
        if matched and union_q == bitset:
            for nid in matched:
                ntype = nodes[nid][0]
                is_dff = "DFF" in ntype.upper()
                semantic[nid]["semantic_group"] = label
                semantic[nid]["role"] = "register" if is_dff else "bus_bit"
                if enc_str:
                    semantic[nid]["state_encoding"] = enc_str

        # 2) netname trung voi driver cua cac bit nay (next-value bundle / ALU macro)
        drivers = {bit_driver.get(b) for b in bits}
        drivers.discard(None)
        driver_union_bits = set()
        for d in drivers:
            driver_union_bits |= qset_by_nid.get(d, set())
        if drivers and driver_union_bits == bitset:
            for d in drivers:
                if not semantic[d]["semantic_group"]:
                    semantic[d]["semantic_group"] = label
                    semantic[d]["role"] = "combinational_source"
                    if enc_str:
                        semantic[d]["state_encoding"] = enc_str

    return semantic


def write_outputs(nodes, order, edges, semantic, nodes_path, edges_path):
    with open(nodes_path, "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["id", "type", "label", "semantic_group", "role", "state_encoding"])
        for nid in order:
            ntype, label = nodes[nid]
            sem = semantic.get(nid, {"semantic_group": "", "role": "", "state_encoding": ""})
            w.writerow([nid, ntype, label, sem["semantic_group"], sem["role"], sem["state_encoding"]])

    with open(edges_path, "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["source", "target", "target_port"])
        w.writerows(edges)


def main():
    if len(sys.argv) < 4:
        print(f"Cach dung: python3 {sys.argv[0]} input.json nodes.csv edges.csv")
        sys.exit(1)
    json_path, nodes_path, edges_path = sys.argv[1:4]

    module_name, mod = load(json_path)
    nodes, order, edges, bit_driver, cell_qbits, cell_type_by_nid = build_base_graph(mod)
    semantic = apply_semantics(mod, nodes, bit_driver, cell_qbits, cell_type_by_nid)
    write_outputs(nodes, order, edges, semantic, nodes_path, edges_path)

    n_labeled = sum(1 for v in semantic.values() if v["semantic_group"])
    n_encoded = sum(1 for v in semantic.values() if v["state_encoding"])
    print(f"Module: {module_name}")
    print(f"Nodes: {len(order)} | Edges: {len(edges)} | Nodes co semantic_group: {n_labeled} | Nodes co state_encoding: {n_encoded}")


if __name__ == "__main__":
    main()
import pytest

from tagbot.masterdata import MasterDataError, load_masterdata


def write(path, text):
    path.write_text(text, encoding="utf-8-sig")


def test_machines_operators_and_carts_are_loaded(tmp_path):
    write(tmp_path / "machines.csv",
          "machine,name,color,multi_type,speed,action,route\n"
          " a2 ,Press 2,ชมพู,N,350,X04,2\n"
          "C4,Press 4,ชมพู,Y,280,,1\n"
          ",,,,,,\n")
    write(tmp_path / "operators.csv", "emp_no,name\nt0001,สมชาย\n")
    write(tmp_path / "carts.csv", "cart\nm04\nM05\n")
    master = load_masterdata(tmp_path)
    a2 = master.machines["A2"]
    assert (a2.name, a2.color, a2.multi_type, a2.speed, a2.action, a2.route) == (
        "Press 2", "ชมพู", False, "350", "X04", 2)
    assert master.machines["C4"].multi_type is True
    assert master.machines["C4"].action == ""
    assert set(master.machines) == {"A2", "C4"}
    assert master.operators == {"T0001": "สมชาย"}
    assert master.carts == {"M04", "M05"}


def test_missing_optional_files_mean_empty_lists(tmp_path):
    write(tmp_path / "machines.csv", "machine,name,color,multi_type,speed,action,route\nA2,,ชมพู,N,350,,\n")
    master = load_masterdata(tmp_path)
    assert master.operators == {}
    assert master.carts == set()
    assert master.machines["A2"].route == 999


def test_missing_column_names_the_file(tmp_path):
    write(tmp_path / "machines.csv", "machine,color\nA2,ชมพู\n")
    with pytest.raises(MasterDataError, match="machines.csv"):
        load_masterdata(tmp_path)


def test_duplicate_machine_is_rejected(tmp_path):
    write(tmp_path / "machines.csv",
          "machine,name,color,multi_type,speed,action,route\nA2,,ชมพู,N,350,,\na2,,เขียว,N,300,,\n")
    with pytest.raises(MasterDataError, match="A2"):
        load_masterdata(tmp_path)


def test_csv_saved_by_excel_in_thai_ansi_encoding_is_read(tmp_path):
    (tmp_path / "machines.csv").write_bytes(
        "machine,name,color,multi_type,speed,action,route\nA2,เครื่องปั๊ม,ชมพู,N,350,,1\n".encode("cp874"))
    master = load_masterdata(tmp_path)
    assert (master.machines["A2"].name, master.machines["A2"].color) == ("เครื่องปั๊ม", "ชมพู")

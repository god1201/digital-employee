from app.domains.knowledge.multimodal import detect_kind, local_extract, parse_table
from app.domains.learning.schemas import ImplicitSignalCreate


def test_detect_kind() -> None:
    assert detect_kind("invoice.png", None) == "image"
    assert detect_kind("call.mp3", None) == "audio"
    assert detect_kind("contract.pdf", "application/pdf") == "pdf"
    assert detect_kind("report.csv", "text/csv") == "table"
    assert detect_kind("notes.txt", "text/plain") == "text"
    assert detect_kind("upload", "image/jpeg") == "image"


def test_parse_table() -> None:
    rows = parse_table("客户,金额,状态\nA,100,已回款\nB,200,逾期\n", "x.csv")
    assert rows[0] == ["客户", "金额", "状态"]
    assert rows[2] == ["B", "200", "逾期"]

    tsv = parse_table("客户\t金额\nA\t100\n", "x.tsv")
    assert tsv[1] == ["A", "100"]


def test_local_extract_text_and_table() -> None:
    text_result = local_extract("notes.txt", "text/plain", "退款政策".encode())
    assert text_result["kind"] == "text"
    assert text_result["text"] == "退款政策"
    assert text_result["provider"] == "local"

    table_result = local_extract("report.csv", "text/csv", b"a,b\n1,2\n")
    assert table_result["kind"] == "table"
    assert table_result["meta"]["rows"] == 2

    json_result = local_extract("data.json", "application/json", b'{"a":1}')
    assert '"a": 1' in json_result["text"]


def test_implicit_signal_schema() -> None:
    signal = ImplicitSignalCreate(content="同一个问题问了三次")
    assert signal.signal_type == "repeat_question"
    assert signal.weight == 1.0

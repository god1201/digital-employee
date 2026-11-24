from app.core.security import hash_password, verify_password
from app.domains.governance.access.service import path_matches
from app.domains.knowledge.embedding import cosine, local_embed
from app.domains.knowledge.graph_rag import expand_neighborhood, rank_entities
from app.domains.operations.alerting import check_condition
from app.domains.skills.tools.executor import render_templates
from app.domains.workflows.storyboards.service import normalize_storyboard
from app.domains.workflows.tasks.worker import is_retryable


def test_password_hash_roundtrip() -> None:
    hashed = hash_password("admin123")
    assert hashed != "admin123"
    assert verify_password("admin123", hashed)
    assert not verify_password("wrong-password", hashed)


def test_path_patterns() -> None:
    assert path_matches("/admin/**", "/admin/users")
    assert path_matches("/admin/**", "/admin/a/b/c")
    assert not path_matches("/admin/**", "/admin")
    assert not path_matches("/admin/**", "/user/admin")

    assert path_matches("/user/*", "/user/123")
    assert not path_matches("/user/*", "/user/123/profile")
    assert path_matches("/user/**", "/user/123/profile")


def test_render_templates() -> None:
    context = {
        "input": {"user_id": 42, "name": "张三"},
        "employee": {"code": "reviewer"},
        "last": {"output": {"id": "abc"}},
    }
    assert render_templates({"id": "{{input.user_id}}"}, context) == {"id": 42}
    assert render_templates("用户-{{input.name}}", context) == "用户-张三"
    assert render_templates("{{last.output.id}}", context) == "abc"
    assert render_templates("{{employee.code}}/profile", context) == "reviewer/profile"
    assert render_templates("{{missing.key}}", context) == "{{missing.key}}"


def test_retryable_classification() -> None:
    assert is_retryable("Python 工具执行失败: timed out")
    assert is_retryable("HTTP 503: service unavailable")
    assert is_retryable("MCP 连接失败: connection refused")
    assert is_retryable("database is locked")
    assert not is_retryable("访问被拒绝：默认拒绝")
    assert not is_retryable("工具不存在或已停用: calc")
    assert not is_retryable("未配置 LLM_API_KEY")
    assert not is_retryable(None)


def test_alert_condition() -> None:
    assert check_condition(1, "gt", 0)
    assert check_condition(1, "gte", 1)
    assert check_condition(0, "lt", 1)
    assert not check_condition(1, "lt", 1)
    assert check_condition(1, "lte", 1)
    assert not check_condition(1, "unknown", 1)


def test_local_embedding() -> None:
    refund_a = local_embed("退款政策：订单签收后 7 天内可以申请无理由退款", 128)
    refund_b = local_embed("退款政策说明，签收后 7 天内支持无理由退款", 128)
    weather = local_embed("今天天气很好，适合出去散步", 128)
    assert len(refund_a) == 128
    assert cosine(refund_a, refund_b) > cosine(refund_a, weather)
    assert cosine(refund_a, refund_a) > 0.99


def test_graph_rag_helpers() -> None:
    entities = [
        {"id": 1, "name": "退款政策", "type": "policy"},
        {"id": 2, "name": "售后服务", "type": "category"},
        {"id": 3, "name": "天气", "type": "topic"},
    ]
    ranked = rank_entities("退款政策怎么处理", entities)
    assert ranked and ranked[0]["id"] == 1

    nodes, edges = expand_neighborhood(
        {1}, [{"id": 1, "source": 1, "target": 2, "type": "属于"}], 1
    )
    assert {1, 2} <= nodes
    assert len(edges) == 1


def test_storyboard_normalize() -> None:
    data = {
        "scenes": [
            {
                "location": "咖啡馆",
                "time_of_day": "夜",
                "characters": "小林, 阿杰",
                "summary": "两人见面",
                "mood": "克制",
                "shots": [
                    {
                        "shot_type": "中景",
                        "camera_movement": "推",
                        "duration_seconds": 999,
                        "description": "小林推门而入",
                        "image_prompt": "",
                    }
                ],
            }
        ]
    }
    result = normalize_storyboard(data, "写实电影感")
    scene = result["scenes"][0]
    assert scene["characters"] == ["小林", "阿杰"]
    shot = scene["shots"][0]
    assert shot["duration_seconds"] == 30
    assert shot["image_prompt"] == "小林推门而入，写实电影感"

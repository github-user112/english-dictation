"""今日动线聚合接口：任务卡从现有学习表实时推导。"""
from datetime import date, datetime, timedelta, timezone

import pytest

from backend.db import db
from backend.today import build_today

USER = "c" * 32
TODAY = date.today().isoformat()
STAMP = datetime.now(timezone.utc).isoformat(timespec="seconds")


def get(client):
    return client.get(f"/api/today?u={USER}")


@pytest.fixture
def conn():
    with db() as c:
        yield c


def add_goal(list_key="test_words", days=30):
    with db() as c:
        c.execute(
            "INSERT INTO study_goal(user,list,target_days,start_day,updated_at) VALUES(?,?,?,?,?)",
            (USER, list_key, days, TODAY, STAMP))


def test_today_fresh_user(client):
    d = get(client).get_json()
    assert d["has_wordtest"] is False
    assert d["all_done"] is False
    assert d["streak"] == 0
    keys = [s["key"] for s in d["steps"]]
    assert keys == ["memorize", "dictation", "arrange", "sentence", "wrong"]
    # 无计划时背词配额走默认 10；错词步无错词即视为完成
    assert d["steps"][0]["target"] == 10
    assert d["steps"][4]["done"] is True
    assert "list=test_words" in d["steps"][0]["link"]
    assert "lesson=1" in d["steps"][3]["link"]


def test_today_uses_goal_quota(client):
    add_goal(days=1)   # 5 个词 1 天背完 → 配额 5
    d = get(client).get_json()
    assert d["goal"]["daily_new"] == 5
    assert d["steps"][0]["target"] == 5
    assert d["steps"][1]["target"] == 5   # min(15, 配额)


def test_today_memorize_progress(client):
    with db() as c:
        for i in (1, 2, 3):
            c.execute(
                "INSERT INTO word_state(user,list,item_id,kind,memorized,memorize_count,last_memorize)"
                " VALUES(?,?,?,'word',1,2,?)", (USER, "test_words", f"w{i}", TODAY))
    d = get(client).get_json()
    step = d["steps"][0]
    assert (step["progress"], step["done"]) == (3, False)


def test_today_dictation_counts_only_target_list(client):
    with db() as c:
        c.execute("INSERT INTO study_session VALUES('s1',?,?,'assisted','memorized','daily',NULL,?,0,'active',?,?,NULL)",
                  (USER, "test_words", TODAY, STAMP, STAMP))
        for i in range(10):
            c.execute("INSERT INTO study_session_item(session_id,seq,item_id,kind,phase,state,final_right)"
                      " VALUES('s1',?,?,'word','new','completed',1)", (i + 1, f"w{i}"))
        # 别的词库的练习不计入目标词库
        c.execute("INSERT INTO study_session VALUES('s2',?,?,'assisted','all','daily',NULL,?,0,'active',?,?,NULL)",
                  (USER, "test_sents", TODAY, STAMP, STAMP))
        c.execute("INSERT INTO study_session_item(session_id,seq,item_id,kind,phase,state,final_right)"
                  " VALUES('s2',1,'1','sentence','new','completed',1)")
    d = get(client).get_json()
    assert d["steps"][1]["progress"] == 10
    assert d["steps"][1]["done"] is True


def test_today_lesson_stays_on_same_day_completion(client):
    """今天完成的课当天不跳：今天打卡的还是这一课；明天才推进。"""
    with db() as c:
        c.execute("INSERT INTO study_session VALUES('s9',?,?,'assisted','all','lesson',1,?,0,'completed',?,?,?)",
                  (USER, "test_sents", TODAY, STAMP, STAMP, STAMP))
    d = get(client).get_json()
    assert d["lesson"] == 1
    assert "lesson=1" in d["steps"][3]["link"]
    # 第 1 课会话是今天完成的 → 句子步直接算完成（不强迫立刻再学第 2 课）
    assert d["steps"][3]["done"] is True


def test_today_lesson_advances_next_day(client):
    yesterday = (date.today() - timedelta(days=1)).isoformat()
    with db() as c:
        c.execute("INSERT INTO study_session VALUES('s9',?,?,'assisted','all','lesson',1,?,0,'completed',?,?,?)",
                  (USER, "test_sents", yesterday, STAMP, STAMP, STAMP))
    d = get(client).get_json()
    assert d["lesson"] == 2
    assert "lesson=2" in d["steps"][3]["link"]
    assert d["steps"][3]["done"] is False


def test_today_cross_day_session_completion_counts_today(client):
    """昨天创建、今天才打完的会话：完成那一刻 assigned_day 重挂到今天，句子步算今天完成。"""
    yesterday = (date.today() - timedelta(days=1)).isoformat()
    with db() as c:
        c.execute("INSERT INTO study_session VALUES('sx',?,?,'assisted','all','lesson',1,?,0,'active',?,?,NULL)",
                  (USER, "test_sents", yesterday, STAMP, STAMP))
        c.execute("INSERT INTO study_session_item(session_id,seq,item_id,kind,phase)"
                  " VALUES('sx',1,'1','sentence','new')")
    client.post(f"/api/result?u={USER}", json={
        "session_id": "sx", "id": "1", "first_right": True,
        "final_right": True, "attempt_count": 1, "outcome": "completed",
    })
    with db() as c:
        row = c.execute("SELECT state, assigned_day FROM study_session WHERE id='sx'").fetchone()
    assert row["state"] == "completed"
    assert row["assigned_day"] == TODAY
    d = get(client).get_json()
    assert d["steps"][3]["done"] is True


def test_today_wrong_step(client):
    with db() as c:
        c.execute(
            "INSERT INTO word_state(user,list,item_id,kind,status,wrong_count,next_review)"
            " VALUES(?,?,?, 'word','learning',2,?)", (USER, "test_words", "w1", TODAY))
    d = get(client).get_json()
    step = d["steps"][4]
    assert step["done"] is False and step["target"] == 1
    assert step["link"] == "#/wrong?from=today"


def test_today_wrong_step_progress(client):
    """错词回收 = 10 词一组（池小按池算）：练几个看 daily_practice_log 的 wrong 桶，练满即完成。"""
    with db() as c:
        for i in range(3):
            c.execute(
                "INSERT INTO word_state(user,list,item_id,kind,status,wrong_count)"
                " VALUES(?,?,?,'word','learning',1)", (USER, "test_words", f"w{i}"))
        c.execute("INSERT INTO daily_practice_log(day,user,practice_mode,review_count)"
                  " VALUES(?,?,'wrong',2)", (TODAY, USER))
    step = get(client).get_json()["steps"][4]
    assert (step["target"], step["progress"], step["done"]) == (3, 2, False)
    with db() as c:
        c.execute("UPDATE daily_practice_log SET review_count=3"
                  " WHERE day=? AND user=? AND practice_mode='wrong'", (TODAY, USER))
    assert get(client).get_json()["steps"][4]["done"] is True


def test_wrong_today_pick(client):
    """回收题组：今天答错且仍在错词本的词优先，其余按到期从错词本补，最多 10 个。"""
    with db() as c:
        c.execute("INSERT INTO study_session VALUES('s1',?,?,'assisted','all','daily',NULL,?,0,'completed',?,?,?)",
                  (USER, "test_words", TODAY, STAMP, STAMP, STAMP))
        c.execute("INSERT INTO study_session_item(session_id,seq,item_id,kind,phase,state,first_right,final_right)"
                  " VALUES('s1',1,'hello','word','new','completed',0,0)")
        c.execute("INSERT INTO word_state(user,list,item_id,kind,status,wrong_count)"
                  " VALUES(?,?,?,'word','learning',2)", (USER, "test_words", "hello"))
        # 旧错词：不在今天答错之列，作补位
        c.execute("INSERT INTO word_state(user,list,item_id,kind,status,wrong_count)"
                  " VALUES(?,?,?,'word','learning',1)", (USER, "test_words", "world"))
        # 已赎出错词本的词不该入选
        c.execute("INSERT INTO word_state(user,list,item_id,kind,status,wrong_count)"
                  " VALUES(?,?,?,'word','learning',0)", (USER, "test_words", "apple"))
    d = client.get(f"/api/wrong/today?u={USER}").get_json()
    ids = [i["id"] for i in d["items"]]
    assert ids[0] == "hello" and "world" in ids and len(ids) == 2


def test_legacy_result_wrong_mode(client):
    """错词回收练习以 mode=wrong 记账：进 daily_practice_log 的 wrong 桶并照常更新 word_state。"""
    r = client.post(f"/api/result?u={USER}", json={
        "list": "test_words", "id": "hello", "mode": "wrong",
        "first_right": True, "final_right": True, "attempt_count": 1, "outcome": "completed"})
    assert r.status_code == 200
    with db() as c:
        row = c.execute(
            "SELECT review_count, final_right_count FROM daily_practice_log"
            " WHERE day=? AND user=? AND practice_mode='wrong'", (TODAY, USER)).fetchone()
        state = c.execute(
            "SELECT right_count FROM word_state WHERE user=? AND list='test_words' AND item_id='hello'",
            (USER,)).fetchone()
    assert row["review_count"] == 1 and row["final_right_count"] == 1
    assert state["right_count"] == 1


def test_today_nce_words_pair_same_book_sentences(client):
    """nceN 词汇必须配 ncN 课文（防切片回归：nce2[2:]=='e2' 曾拼出 ne2）。"""
    from backend.today import _pick_lists
    fake = {"nce2": {"type": "words", "title": "w"}, "nc2": {"type": "sentences", "title": "s"}}
    from unittest.mock import patch
    with patch("backend.today.MATERIALS", fake), db() as c:
        assert _pick_lists(c, USER, None) == ("nce2", "nc2")


def test_today_wordtest_recommendation(client):
    with db() as c:
        c.execute(
            "INSERT INTO wordtest_result(user,level,questions_answered,correct_count,cefr,word_count,detail,created_at)"
            " VALUES(?,7,25,18,'B1',3500,'[]',?)", (USER, STAMP))
    d = get(client).get_json()
    assert d["has_wordtest"] is True and d["wordtest"]["cefr"] == "B1"
    # B1 → nce2/nc2，但测试环境没有这两个素材 → 退到同类第一个
    assert d["word_list"]["key"] == "test_words"
    assert d["sent_list"]["key"] == "test_sents"


def get_nce(client):
    """课程模式：test_nce 词库（课号 1,3）+ test_sents 句库（课号 1,2）。"""
    return client.get(f"/api/today?u={USER}&list=test_nce")


def test_lesson_mode_layout(client):
    d = get_nce(client).get_json()
    assert d["lesson_mode"] is True
    assert d["goal"] is None                      # 按课不按量，学习计划不参与
    assert d["lesson"] == 1 and d["lesson_total"] == 2
    keys = [s["key"] for s in d["steps"]]
    assert keys == ["memorize", "dictation", "arrange", "sentence", "wrong"]
    mem, dic = d["steps"][:2]
    arr, sent = d["steps"][2], d["steps"][3]
    assert mem["target"] == 2 and mem["desc"] == "第 1 课 · 2 个单词"
    assert "list=test_nce&lesson=1" in mem["link"]
    assert "list=test_nce&lesson=1" in dic["link"] and dic["link"].endswith("from=today")
    assert arr["link"].startswith("#/arrange?list=test_sents&lesson=1")
    assert "list=test_sents&lesson=1" in sent["link"]
    assert sent["target"] == 2                    # test_sents 第 1 课 2 句


def test_lesson_mode_word_lesson_mapping(client):
    """句库第 2 课 ↔ 词库第 3 课（nce1 双课合并：词课号 = 2L-1）。"""
    yesterday = (date.today() - timedelta(days=1)).isoformat()
    with db() as c:
        c.execute("INSERT INTO study_session VALUES('s9',?,?,'assisted','all','lesson',1,?,0,'completed',?,?,?)",
                  (USER, "test_sents", yesterday, STAMP, STAMP, STAMP))
    d = get_nce(client).get_json()
    assert d["lesson"] == 2
    mem = d["steps"][0]
    assert mem["desc"] == "第 2 课 · 2 个单词"
    assert "lesson=3" in mem["link"]                  # 词库课号 2L-1
    assert "lesson=3" in d["steps"][1]["link"]
    assert "list=test_sents&lesson=2" in d["steps"][3]["link"]   # 句库课号不变


def test_lesson_mode_word_steps_completion(client):
    with db() as c:
        for w in ("excuse", "pardon"):
            c.execute(
                "INSERT INTO word_state(user,list,item_id,kind,memorized,memorize_count,last_memorize)"
                " VALUES(?,?,?,'word',1,2,?)", (USER, "test_nce", w, TODAY))
        # 整课听打会话打完即算完成，哪怕有词最终没拼对（错词本兜底回收）
        c.execute("INSERT INTO study_session VALUES('w1',?,?,'assisted','all','lesson',1,?,0,'completed',?,?,?)",
                  (USER, "test_nce", TODAY, STAMP, STAMP, STAMP))
        c.execute("INSERT INTO study_session_item(session_id,seq,item_id,kind,phase,state,final_right)"
                  " VALUES('w1',1,'excuse','word','new','completed',1)")
        c.execute("INSERT INTO study_session_item(session_id,seq,item_id,kind,phase,state,final_right)"
                  " VALUES('w1',2,'pardon','word','new','completed',0)")
    d = get_nce(client).get_json()
    mem, dic = d["steps"][:2]
    assert mem["done"] is True and mem["progress"] == 2
    assert dic["done"] is True and dic["progress"] == 1


def test_word_lesson_mapping():
    from backend.today import _word_lesson
    assert _word_lesson([1, 3, 5], [1, 2, 3], 2) == 3       # nce1 双课合并
    assert _word_lesson([1, 2, 3], [1, 2, 3], 2) == 2       # 课号一致的册
    assert _word_lesson([1, 2, 4], [1, 2, 3, 4], 3) is None  # 词库缺课（如 nce4 第 21 课）
    assert _word_lesson([1, 2], [1, 2, 3], 3) is None        # 课号超出词库范围
    assert _word_lesson([], [1], 1) is None


def test_lesson_mode_same_lesson_two_sessions(client):
    """同课两个会话：昨天完成的 + 今天重练中的 → 留在本课，且句子步不算完成（完成只看今天）。"""
    yesterday = (date.today() - timedelta(days=1)).isoformat()
    with db() as c:
        c.execute("INSERT INTO study_session VALUES('s1',?,?,'assisted','all','lesson',1,?,0,'completed',?,?,?)",
                  (USER, "test_sents", yesterday, STAMP, STAMP, STAMP))
        c.execute("INSERT INTO study_session VALUES('s2',?,?,'assisted','all','lesson',1,?,0,'active',?,?,NULL)",
                  (USER, "test_sents", TODAY, STAMP, STAMP))
    d = get_nce(client).get_json()
    assert d["lesson"] == 1
    assert d["steps"][3]["done"] is False


def test_today_all_done(client):
    with db() as c:
        for i in range(10):
            c.execute(
                "INSERT INTO word_state(user,list,item_id,kind,memorized,memorize_count,last_memorize)"
                " VALUES(?,?,?,'word',1,2,?)", (USER, "test_words", f"w{i}", TODAY))
        c.execute("INSERT INTO study_session VALUES('s1',?,?,'assisted','memorized','daily',NULL,?,0,'completed',?,?,?)",
                  (USER, "test_words", TODAY, STAMP, STAMP, STAMP))
        c.execute("INSERT INTO study_session VALUES('s2',?,?,'assisted','all','lesson',1,?,0,'completed',?,?,?)",
                  (USER, "test_sents", TODAY, STAMP, STAMP, STAMP))
        for i in range(15):
            c.execute("INSERT INTO study_session_item(session_id,seq,item_id,kind,phase,state,final_right)"
                      " VALUES('s1',?,?,'word','new','completed',1)", (i + 1, f"w{i}"))
        c.execute("INSERT INTO daily_practice_log(day,user,practice_mode,final_right_count)"
                  " VALUES(?,?,'arrange',5)", (TODAY, USER))
        c.execute("INSERT INTO daily_challenge(day,user,list_key,score,total,detail,completed_at)"
                  " VALUES(?,?,'test_words',8,10,'[]',?)", (TODAY, USER, STAMP))
    d = get(client).get_json()
    assert d["all_done"] is True
    assert d["done_count"] == len(d["steps"])
    assert d["daily_done"] is True
    assert d["streak"] == 1


def test_today_respects_tz_header(client):
    """X-Tz-Offset 头决定「今天」的归属：UTC+8 用户的日期 = UTC 时刻 +8h 的日期。
    与不带头时退回 date.today() 的旧行为互不干扰。"""
    expect = (datetime.now(timezone.utc) + timedelta(hours=8)).date().isoformat()
    d = client.get(f"/api/today?u={USER}", headers={"X-Tz-Offset": "-480"}).get_json()
    assert d["date"] == expect
    d = client.get(f"/api/today?u={USER}", headers={"X-Tz-Offset": "garbage"}).get_json()
    assert d["date"] == TODAY   # 非法头退回服务器本地日期（旧行为）


# ---- 课程选择器：显式选课 + 复习模式 ----

def test_today_lesson_options_returned(client):
    """lesson_options 返回该句库所有课的完成状态。"""
    d = get_nce(client).get_json()
    assert d["lesson_options"] == [
        {"n": 1, "done_today": False, "done_ever": False},
        {"n": 2, "done_today": False, "done_ever": False},
    ]
    assert d["review_mode"] is False


def test_today_lesson_options_marks_done(client):
    """已完成的课标记 done_ever=True；今天完成的标记 done_today=True。"""
    yesterday = (date.today() - timedelta(days=1)).isoformat()
    with db() as c:
        # 第 1 课昨天完成
        c.execute("INSERT INTO study_session VALUES('s1',?,?,'assisted','all','lesson',1,?,0,'completed',?,?,?)",
                  (USER, "test_sents", yesterday, STAMP, STAMP, STAMP))
        # 第 2 课今天完成
        c.execute("INSERT INTO study_session VALUES('s2',?,?,'assisted','all','lesson',2,?,0,'completed',?,?,?)",
                  (USER, "test_sents", TODAY, STAMP, STAMP, STAMP))
    d = get_nce(client).get_json()
    opts = {o["n"]: o for o in d["lesson_options"]}
    assert opts[1]["done_ever"] is True and opts[1]["done_today"] is False
    assert opts[2]["done_ever"] is True and opts[2]["done_today"] is True


def test_today_lesson_param_selects_specific_lesson(client):
    """?lesson=2 选择第 2 课，覆盖自动推导。"""
    d = client.get(f"/api/today?u={USER}&list=test_nce&lesson=2").get_json()
    assert d["lesson"] == 2
    assert "lesson=2" in d["steps"][3]["link"]   # 句子步指向第 2 课


def test_today_review_mode_true_for_completed_lesson(client):
    """选了已完成的课 → review_mode=True，所有环节可自由练习。"""
    yesterday = (date.today() - timedelta(days=1)).isoformat()
    with db() as c:
        c.execute("INSERT INTO study_session VALUES('s1',?,?,'assisted','all','lesson',1,?,0,'completed',?,?,?)",
                  (USER, "test_sents", yesterday, STAMP, STAMP, STAMP))
    d = client.get(f"/api/today?u={USER}&list=test_nce&lesson=1").get_json()
    assert d["review_mode"] is True


def test_today_review_mode_false_for_current_lesson(client):
    """当前课（未完成的）→ review_mode=False，线性锁定。"""
    d = get_nce(client).get_json()
    assert d["review_mode"] is False


def test_today_review_mode_after_all_done(client):
    """当前课今天全部完成 → review_mode=True，允许继续自由练习。"""
    with db() as c:
        c.execute("INSERT INTO study_session VALUES('s1',?,?,'assisted','all','lesson',1,?,0,'completed',?,?,?)",
                  (USER, "test_sents", TODAY, STAMP, STAMP, STAMP))
    d = get_nce(client).get_json()
    # 第 1 课今天完成 → review_mode 为 True
    assert d["review_mode"] is True


def test_today_lesson_param_invalid_falls_back(client):
    """?lesson=999 无效课号 → 回退到自动推导的当前课。"""
    d = client.get(f"/api/today?u={USER}&list=test_nce&lesson=999").get_json()
    assert d["lesson"] == 1   # 无完成会话时默认第 1 课

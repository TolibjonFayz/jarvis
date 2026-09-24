"""Agent mantiqi: yo'nalishlar, halollik himoyasi, FINAL, buzuq tool chaqiruvi."""
import time

import pytest

import agent
import memory
from conftest import CHAT, ToolUseFailed, reply


# --- Yo'nalishlar (router'ni chetlab o'tish) ---

@pytest.mark.parametrize("text,cats", [
    ("bu hafta nima bor?", ["kal"]),                      # yo'q eslatmani to'qigan edi
    ("ertaga soat 7 da uyg'otishni eslat", ["esl", "todo"]),
    ("eslatmalarim", ["esl", "todo"]),
    ("barcha todolarni o'chir", ["esl", "todo"]),
    ("kun.uz kanalini dayjestga qo'sh", ["dayjest", "tg"]),
    ("IMAN kanalidan chiqib ket", ["tg"]),
    ("Unilance ni pin qil", ["tg"]),
    ("kimga javob bermadim?", ["tg"]),
    ("ERP'da shu oy nima o'zgardi?", ["loyiha"]),          # router "ma'lumot yo'q" degan edi
    ("bugun nima qildim?", ["loyiha"]),
    ("ertangi test uchrashuvni o'chir", ["kal"]),
])
def test_forced_routes(text, cats):
    assert agent.forced_categories(text) == cats


@pytest.mark.parametrize("text", ["salom bro", "python'da list nima?", "havo o'zgardimi?", "rahmat"])
def test_no_forced_route_for_chat(text):
    assert agent.forced_categories(text) is None


@pytest.mark.parametrize("text,is_money", [
    ("taksi 25 ming", True), ("obed 45k", True), ("svetga 1.2 mln to'ladim", True),
    ("bu oy qancha sarfladim?", True), ("oxirgi xarajatni o'chir", True),
    ("ovqatga oyiga 2 mln budjet", True), ("50 so'm", True),
    ("salom", False), ("2026 yil rejalar", False), ("5 km yugurdim", False),
])
def test_money_detection(text, is_money):
    assert bool(agent._MONEY_RE.search(agent._APOS_RE.sub("", text))) == is_money


def test_unknown_category_sends_small_toolset():
    # Avval hamma 48 tool (~4800 token) ketardi — daqiqalik limitni yerdi.
    names = [t["function"]["name"] for t in agent._subset_tools([])]
    assert names and len(names) <= 5


def test_retry_after_parsing():
    assert agent._retry_after(Exception("Please try again in 4.72s.")) == pytest.approx(4.72)
    assert agent._retry_after(Exception("try again in 2m27.3s")) == pytest.approx(147.3)
    assert agent._retry_after(Exception("boshqa xato")) is None


# --- Halollik: "o'chirildi" deyish uchun o'zgartiruvchi tool chaqirilgan bo'lishi shart ---

def test_claim_without_mutation_is_not_passed_to_user(llm):
    script = llm(
        reply("", [("list_todos", {})]),                     # faqat ko'rdi
        reply("Barcha to-do'lar o'chirildi ✅"),              # ...va yolg'on aytdi
        reply("Hammasi o'chirildi"),                         # eslatmadan keyin ham
    )
    out = agent._tool_loop(CHAT, [], "todolarni o'chir", ["todo"])
    assert "bajara olmadim" in out
    assert "[Tizim]" in script.requests[2]["messages"][-1]["content"]


def test_claim_after_real_mutation_is_fine(llm):
    memory.add_todo(CHAT, "non olish")
    llm(reply("", [("complete_todo", {"all": True})]), reply("Hammasi bajarildi ✅"))
    out = agent._tool_loop(CHAT, [], "todolarni o'chir", ["todo"])
    assert out == "Hammasi bajarildi ✅"
    assert memory.list_todos(CHAT) == []


# --- FINAL: ro'yxat so'zma-so'z, lekin "o'chir" so'ralsa oraliq qadam ---

def test_final_list_returned_verbatim(llm):
    memory.add_recurring(CHAT, "tabletka", 9, 0)
    llm(reply("", [("list_reminders", {})]))
    out = agent._tool_loop(CHAT, [], "eslatmalarim", ["esl"])
    assert "🔁 **Takroriy** (1)" in out and "tabletka" in out


def test_final_list_does_not_stop_deletion(llm):
    # Avval ro'yxat chiqib, o'chirish bajarilmay qolardi.
    memory.add_recurring(CHAT, "tabletka", 9, 0)
    memory.add_reminder(CHAT, "qo'ng'iroq", time.time() + 3600)
    llm(
        reply("", [("list_reminders", {})]),
        reply("", [("cancel_recurring", {"all": True}), ("cancel_reminder", {"all": True})]),
        reply("Hammasi o'chirildi."),
    )
    out = agent._tool_loop(CHAT, [], "eslatmalarni hammasini o'chirib tashla", ["esl"])
    assert memory.list_recurring(CHAT) == []
    assert memory.pending_reminders_with_id(CHAT) == []
    assert "o'chirildi" in out


# --- Buzuq tool chaqiruvi: niyati bajariladi, bot yiqilmaydi ---

def test_tool_use_failed_is_salvaged(llm):
    memory.add_todo(CHAT, "kitob o'qish")
    llm(ToolUseFailed("list_todos", {}), reply("Bitta vazifa bor."))
    out = agent._tool_loop(CHAT, [], "vazifalarim", ["todo"])
    assert out  # yiqilmadi


def test_tool_use_failed_twice_does_not_crash(llm):
    llm(ToolUseFailed("noma_lum_tool", {}), ToolUseFailed("noma_lum_tool", {}))
    out = agent._tool_loop(CHAT, [], "nimadir", ["todo"])
    assert "tushunishda xato" in out


def test_forced_route_requires_tool_on_first_step(llm):
    script = llm(reply("", [("list_reminders", {})]))
    agent._tool_loop(CHAT, [], "eslatmalarim", ["esl"], require=True)
    assert script.requests[0]["tool_choice"] == "required"


# --- Pul oqimi: summa so'zma-so'z bazadan ---

def test_money_flow_verbatim(llm):
    llm(reply("", [("add_expense", {"items": [
        {"amount": 25000, "category": "transport", "note": "taksi"},
        {"amount": 45000, "category": "ovqat", "note": "obed"},
    ]})]))
    out = agent.respond(CHAT, "taksi 25 ming, obed 45k")
    assert "25 000 so'm" in out and "45 000 so'm" in out and "70 000 so'm" in out


def test_money_flow_null_field_salvaged(llm):
    # Model ixtiyoriy maydonga null yuborsa Groq rad etardi -> jim o'tib ketardi.
    memory.add_expense(CHAT, 190000, "ovqat", "obed", time.strftime("%Y-%m-%d"))
    llm(ToolUseFailed("expense_report", {"period": "oy", "category": None}))
    out = agent.respond(CHAT, "bu oy qancha sarfladim?")
    assert "190 000 so'm" in out

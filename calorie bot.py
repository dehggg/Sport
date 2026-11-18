import asyncio
import os
import sqlite3
from contextlib import closing

from aiogram import Bot, Dispatcher, F
from aiogram.filters import Command, CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import (
    CallbackQuery,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    Message,
)

DB_PATH = "bot.db"

ACTIVITY = [
    ("Сидячий спосіб життя", 1.2),
    ("Легка (1-3 тренування на тиждень)", 1.375),
    ("Помірна (3-5 тренувань на тиждень)", 1.55),
    ("Висока (6-7 тренувань на тиждень)", 1.725),
]
GOALS = {"lose": "Схуднути", "keep": "Тримати вагу", "gain": "Набрати вагу"}

dp = Dispatcher()


class Form(StatesGroup):
    sex = State()
    age = State()
    height = State()
    weight = State()
    activity = State()
    goal = State()


def init_db():
    with closing(sqlite3.connect(DB_PATH)) as conn:
        conn.execute(
            """CREATE TABLE IF NOT EXISTS users (
                user_id INTEGER PRIMARY KEY,
                sex TEXT,
                age INTEGER,
                height REAL,
                weight REAL,
                activity INTEGER,
                goal TEXT
            )"""
        )
        conn.commit()


def save_user(user_id, row):
    with closing(sqlite3.connect(DB_PATH)) as conn:
        conn.execute(
            "INSERT OR REPLACE INTO users VALUES (?, ?, ?, ?, ?, ?, ?)",
            (user_id, *row),
        )
        conn.commit()


def load_user(user_id):
    with closing(sqlite3.connect(DB_PATH)) as conn:
        return conn.execute(
            "SELECT sex, age, height, weight, activity, goal FROM users WHERE user_id = ?",
            (user_id,),
        ).fetchone()


def calculate(sex, age, height, weight, activity, goal):
    h = height / 100
    bmi = weight / h**2
    low, high = 18.5 * h**2, 24.9 * h**2
    inches_over = max(0.0, (height - 152.4) / 2.54)
    devine = (50 if sex == "m" else 45.5) + 2.3 * inches_over

    bmr = 10 * weight + 6.25 * height - 5 * age + (5 if sex == "m" else -161)
    tdee = bmr * ACTIVITY[activity][1]
    floor = 1500 if sex == "m" else 1200
    if goal == "lose":
        kcal = max(tdee * 0.85, floor)
    elif goal == "gain":
        kcal = tdee * 1.1
    else:
        kcal = tdee

    protein = weight * (1.6 if goal == "keep" else 1.8)
    fat = weight * 0.9
    carbs = max(0.0, (kcal - protein * 4 - fat * 9) / 4)
    water = weight * 0.032 + (0.5 if activity >= 2 else 0)

    return {
        "bmi": bmi,
        "low": low,
        "high": high,
        "devine": devine,
        "kcal": kcal,
        "protein": protein,
        "fat": fat,
        "carbs": carbs,
        "water": water,
    }


def format_result(sex, age, height, weight, activity, goal):
    r = calculate(sex, age, height, weight, activity, goal)
    return (
        "📊 Твій профіль\n"
        f"ІМТ: {r['bmi']:.1f}\n"
        f"Здоровий діапазон ваги: {r['low']:.1f}–{r['high']:.1f} кг\n"
        f"За формулою Девіна: {r['devine']:.1f} кг (орієнтир)\n\n"
        f"🎯 Денна норма ({GOALS[goal]})\n"
        f"Калорії: {r['kcal']:.0f} ккал\n"
        f"Білки: {r['protein']:.0f} г\n"
        f"Жири: {r['fat']:.0f} г\n"
        f"Вуглеводи: {r['carbs']:.0f} г\n\n"
        f"💧 Вода: {r['water']:.1f} л на день\n\n"
        "ІМТ неточний для людей з великою м'язовою масою. "
        "Це орієнтовні розрахунки, а не медична порада."
    )


def kb(rows):
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text=text, callback_data=data)] for text, data in rows
        ]
    )


def parse(text, lo, hi):
    try:
        value = float(text.replace(",", "."))
    except (ValueError, AttributeError):
        return None
    return value if lo <= value <= hi else None


@dp.message(CommandStart())
async def start(m: Message, state: FSMContext):
    await state.clear()
    await state.set_state(Form.sex)
    await m.answer(
        "Привіт! Я порахую твою норму калорій, БЖВ, води та здоровий діапазон ваги.\n"
        "Бот для користувачів від 18 років.\n\nОбери стать:",
        reply_markup=kb([("Чоловік", "sex:m"), ("Жінка", "sex:f")]),
    )


@dp.callback_query(Form.sex, F.data.startswith("sex:"))
async def got_sex(c: CallbackQuery, state: FSMContext):
    await state.update_data(sex=c.data.split(":")[1])
    await state.set_state(Form.age)
    await c.message.answer("Скільки тобі років?")
    await c.answer()


@dp.message(Form.age)
async def got_age(m: Message, state: FSMContext):
    value = parse(m.text, 18, 80)
    if value is None:
        await m.answer("Введи вік числом від 18 до 80.")
        return
    await state.update_data(age=int(value))
    await state.set_state(Form.height)
    await m.answer("Зріст у см (наприклад, 175):")


@dp.message(Form.height)
async def got_height(m: Message, state: FSMContext):
    value = parse(m.text, 120, 230)
    if value is None:
        await m.answer("Введи зріст у см, від 120 до 230.")
        return
    await state.update_data(height=value)
    await state.set_state(Form.weight)
    await m.answer("Вага в кг (наприклад, 68.5):")


@dp.message(Form.weight)
async def got_weight(m: Message, state: FSMContext):
    value = parse(m.text, 35, 250)
    if value is None:
        await m.answer("Введи вагу в кг, від 35 до 250.")
        return
    await state.update_data(weight=value)
    await state.set_state(Form.activity)
    await m.answer(
        "Рівень активності:",
        reply_markup=kb([(name, f"act:{i}") for i, (name, _) in enumerate(ACTIVITY)]),
    )


@dp.callback_query(Form.activity, F.data.startswith("act:"))
async def got_activity(c: CallbackQuery, state: FSMContext):
    await state.update_data(activity=int(c.data.split(":")[1]))
    await state.set_state(Form.goal)
    await c.message.answer(
        "Яка ціль?",
        reply_markup=kb([(name, f"goal:{key}") for key, name in GOALS.items()]),
    )
    await c.answer()


@dp.callback_query(Form.goal, F.data.startswith("goal:"))
async def got_goal(c: CallbackQuery, state: FSMContext):
    goal = c.data.split(":")[1]
    data = await state.get_data()
    bmi = data["weight"] / (data["height"] / 100) ** 2
    note = ""
    if goal == "lose" and bmi < 20:
        goal = "keep"
        note = (
            "⚠️ При твоєму ІМТ худнути не варто, тому розрахунок "
            "зроблено для підтримки ваги.\n\n"
        )
    row = (
        data["sex"],
        data["age"],
        data["height"],
        data["weight"],
        data["activity"],
        goal,
    )
    save_user(c.from_user.id, row)
    await state.clear()
    await c.message.answer(note + format_result(*row))
    await c.answer()


@dp.message(Command("profile"))
async def profile(m: Message):
    row = load_user(m.from_user.id)
    if not row:
        await m.answer("Профілю ще немає. Натисни /start.")
        return
    await m.answer(format_result(*row))


async def main():
    token = os.getenv("BOT_TOKEN")
    if not token:
        raise SystemExit("Задай змінну середовища BOT_TOKEN")
    init_db()
    await dp.start_polling(Bot(token))


if __name__ == "__main__":
    asyncio.run(main())

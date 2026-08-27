#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
Bot Telegram d'analyse de football (fichier unique)
----------------------------------------------------
Ce bot utilise l'API gratuite TheSportsDB pour :
- Comparer les tendances des matchs terminés (hier vs aujourd'hui)
- Lister les matchs à venir dans un créneau configurable (par défaut 30 min)
- S'adapter au fuseau horaire (par défaut Africa/Douala)

Configuration via variables d'environnement ou fichier .env :
  TELEGRAM_BOT_TOKEN  (obligatoire)
  TIMEZONE            (défaut: Africa/Douala)
  LANGUAGE            (fr/en, défaut: fr)
  UPCOMING_MINUTES    (défaut: 30)
  LOG_LEVEL           (défaut: INFO)
  LOG_FILE            (vide = console)

Installation :
  pip install python-telegram-bot requests python-dotenv
  Créer un fichier .env avec au moins TELEGRAM_BOT_TOKEN=votre_token
  Lancer : python bot.py
"""

import os
import logging
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo
from typing import List, Dict, Any

import requests
from dotenv import load_dotenv
from telegram import Update
from telegram.ext import Application, CommandHandler, ContextTypes

# Charger les variables depuis .env si présent
load_dotenv()

# ------------------- CONFIGURATION -------------------
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
if not TELEGRAM_BOT_TOKEN:
    raise ValueError("La variable d'environnement TELEGRAM_BOT_TOKEN est requise.")

TIMEZONE_STR = os.getenv("TIMEZONE", "Africa/Douala")
try:
    TZ = ZoneInfo(TIMEZONE_STR)
except Exception:
    raise ValueError(f"Fuseau horaire invalide : {TIMEZONE_STR}")

LANGUAGE = os.getenv("LANGUAGE", "fr").lower()
if LANGUAGE not in ["fr", "en"]:
    raise ValueError("LANGUAGE doit être 'fr' ou 'en'.")

try:
    UPCOMING_MINUTES = int(os.getenv("UPCOMING_MINUTES", "30"))
except ValueError:
    UPCOMING_MINUTES = 30

LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO").upper()
LOG_FILE = os.getenv("LOG_FILE", "")

# Configuration du logging
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=getattr(logging, LOG_LEVEL, logging.INFO)
)
if LOG_FILE:
    file_handler = logging.FileHandler(LOG_FILE)
    file_handler.setFormatter(logging.Formatter("%(asctime)s - %(name)s - %(levelname)s - %(message)s"))
    logging.getLogger().addHandler(file_handler)

logger = logging.getLogger(__name__)

# ------------------- API FOOTBALL -------------------
API_BASE_URL = "https://www.thesportsdb.com/api/v1/json/3"

def get_events_for_date(date_str: str, retries: int = 3) -> List[Dict[str, Any]]:
    """Récupère les événements de football pour une date donnée (YYYY-MM-DD)."""
    url = f"{API_BASE_URL}/eventsday.php?d={date_str}&s=Soccer"
    for attempt in range(retries):
        try:
            response = requests.get(url, timeout=10)
            response.raise_for_status()
            data = response.json()
            events = data.get("events", [])
            return events if events else []
        except requests.exceptions.RequestException as e:
            logger.warning(f"Tentative {attempt+1}/{retries} échouée pour {date_str}: {e}")
            if attempt == retries - 1:
                logger.error(f"Impossible de récupérer les événements pour {date_str}")
                return []
    return []

def filter_finished_matches(events: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Filtre les matchs terminés."""
    return [ev for ev in events if ev.get("strStatus") == "Match Finished"]

def filter_upcoming_matches(events: List[Dict[str, Any]], now: datetime,
                            delta_minutes: int, tz) -> List[Dict[str, Any]]:
    """Filtre les matchs dont le coup d'envoi est entre now et now+delta_minutes."""
    upcoming = []
    for ev in events:
        if ev.get("strStatus") != "Not Started":
            continue
        timestamp_str = ev.get("strTimestamp")
        if not timestamp_str:
            continue
        try:
            match_time = datetime.fromtimestamp(int(timestamp_str), tz=tz)
        except (ValueError, TypeError):
            continue
        if now <= match_time <= now + timedelta(minutes=delta_minutes):
            upcoming.append(ev)
    return upcoming

def compute_trends(events: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Calcule les statistiques sur une liste de matchs terminés."""
    if not events:
        return {
            "nb_matchs": 0,
            "home_wins": 0,
            "draws": 0,
            "away_wins": 0,
            "total_goals": 0,
            "avg_goals": 0.0,
            "home_goals": 0,
            "away_goals": 0
        }
    home_wins = draws = away_wins = total_goals = home_goals = away_goals = 0
    nb = len(events)
    for ev in events:
        try:
            hg = int(ev.get("intHomeScore", 0) or 0)
            ag = int(ev.get("intAwayScore", 0) or 0)
        except (ValueError, TypeError):
            hg = ag = 0
        home_goals += hg
        away_goals += ag
        total_goals += hg + ag
        if hg > ag:
            home_wins += 1
        elif hg < ag:
            away_wins += 1
        else:
            draws += 1
    avg_goals = total_goals / nb if nb > 0 else 0.0
    return {
        "nb_matchs": nb,
        "home_wins": home_wins,
        "draws": draws,
        "away_wins": away_wins,
        "total_goals": total_goals,
        "avg_goals": round(avg_goals, 2),
        "home_goals": home_goals,
        "away_goals": away_goals
    }

# ------------------- FORMATAGE DES MESSAGES -------------------
def format_trends_message(y_trends: Dict[str, Any], t_trends: Dict[str, Any],
                          lang: str) -> str:
    """Formate le message de comparaison des tendances."""
    if lang == "en":
        msg = "📊 *Trends of matches already played*\n\n"
        msg += f"*Yesterday* ({y_trends['nb_matchs']} matches)\n"
        msg += f"🏠 Home wins: {y_trends['home_wins']}\n"
        msg += f"🤝 Draws: {y_trends['draws']}\n"
        msg += f"✈️ Away wins: {y_trends['away_wins']}\n"
        msg += f"⚽ Goals (home/away/total): {y_trends['home_goals']}/{y_trends['away_goals']}/{y_trends['total_goals']}\n"
        msg += f"📈 Average goals/match: {y_trends['avg_goals']}\n\n"
        msg += f"*Today (already played)* ({t_trends['nb_matchs']} matches)\n"
        msg += f"🏠 Home wins: {t_trends['home_wins']}\n"
        msg += f"🤝 Draws: {t_trends['draws']}\n"
        msg += f"✈️ Away wins: {t_trends['away_wins']}\n"
        msg += f"⚽ Goals (home/away/total): {t_trends['home_goals']}/{t_trends['away_goals']}/{t_trends['total_goals']}\n"
        msg += f"📈 Average goals/match: {t_trends['avg_goals']}\n\n"
        msg += "🔎 *Comparison*\n"
        msg += f"• Home wins: {'⬆️' if t_trends['home_wins'] > y_trends['home_wins'] else '⬇️' if t_trends['home_wins'] < y_trends['home_wins'] else '➡️'} (yesterday {y_trends['home_wins']} → today {t_trends['home_wins']})\n"
        msg += f"• Draws: {'⬆️' if t_trends['draws'] > y_trends['draws'] else '⬇️' if t_trends['draws'] < y_trends['draws'] else '➡️'} (yesterday {y_trends['draws']} → today {t_trends['draws']})\n"
        msg += f"• Away wins: {'⬆️' if t_trends['away_wins'] > y_trends['away_wins'] else '⬇️' if t_trends['away_wins'] < y_trends['away_wins'] else '➡️'} (yesterday {y_trends['away_wins']} → today {t_trends['away_wins']})\n"
        msg += f"• Average goals: {'⬆️' if t_trends['avg_goals'] > y_trends['avg_goals'] else '⬇️' if t_trends['avg_goals'] < y_trends['avg_goals'] else '➡️'} (yesterday {y_trends['avg_goals']} → today {t_trends['avg_goals']})"
    else:  # français
        msg = "📊 *Tendances des matchs déjà joués*\n\n"
        msg += f"*Hier* ({y_trends['nb_matchs']} matchs)\n"
        msg += f"🏠 Victoires à domicile : {y_trends['home_wins']}\n"
        msg += f"🤝 Nuls : {y_trends['draws']}\n"
        msg += f"✈️ Victoires à l'extérieur : {y_trends['away_wins']}\n"
        msg += f"⚽ Buts (dom/ext/total) : {y_trends['home_goals']}/{y_trends['away_goals']}/{y_trends['total_goals']}\n"
        msg += f"📈 Moyenne de buts/match : {y_trends['avg_goals']}\n\n"
        msg += f"*Aujourd'hui (déjà joués)* ({t_trends['nb_matchs']} matchs)\n"
        msg += f"🏠 Victoires à domicile : {t_trends['home_wins']}\n"
        msg += f"🤝 Nuls : {t_trends['draws']}\n"
        msg += f"✈️ Victoires à l'extérieur : {t_trends['away_wins']}\n"
        msg += f"⚽ Buts (dom/ext/total) : {t_trends['home_goals']}/{t_trends['away_goals']}/{t_trends['total_goals']}\n"
        msg += f"📈 Moyenne de buts/match : {t_trends['avg_goals']}\n\n"
        msg += "🔎 *Comparaison*\n"
        msg += f"• Victoires à domicile : {'⬆️' if t_trends['home_wins'] > y_trends['home_wins'] else '⬇️' if t_trends['home_wins'] < y_trends['home_wins'] else '➡️'} (hier {y_trends['home_wins']} → aujourd'hui {t_trends['home_wins']})\n"
        msg += f"• Nuls : {'⬆️' if t_trends['draws'] > y_trends['draws'] else '⬇️' if t_trends['draws'] < y_trends['draws'] else '➡️'} (hier {y_trends['draws']} → aujourd'hui {t_trends['draws']})\n"
        msg += f"• Victoires à l'extérieur : {'⬆️' if t_trends['away_wins'] > y_trends['away_wins'] else '⬇️' if t_trends['away_wins'] < y_trends['away_wins'] else '➡️'} (hier {y_trends['away_wins']} → aujourd'hui {t_trends['away_wins']})\n"
        msg += f"• Moyenne de buts : {'⬆️' if t_trends['avg_goals'] > y_trends['avg_goals'] else '⬇️' if t_trends['avg_goals'] < y_trends['avg_goals'] else '➡️'} (hier {y_trends['avg_goals']} → aujourd'hui {t_trends['avg_goals']})"
    return msg

def format_upcoming_message(matches: List[Dict[str, Any]], lang: str,
                            upcoming_minutes: int) -> str:
    """Formate le message pour les matchs à venir."""
    if not matches:
        return "Aucun match ne commence dans les {} prochaines minutes.".format(upcoming_minutes) if lang == "fr" else "No match starts in the next {} minutes.".format(upcoming_minutes)
    if lang == "en":
        msg = f"⏰ *Matches starting in the next {upcoming_minutes} minutes* (time zone: {TIMEZONE_STR})\n\n"
    else:
        msg = f"⏰ *Matchs à venir dans les {upcoming_minutes} prochaines minutes* (heure de Douala)\n\n"
    for ev in matches:
        home = ev.get("strHomeTeam", "?")
        away = ev.get("strAwayTeam", "?")
        league = ev.get("strLeague", "?")
        timestamp = int(ev.get("strTimestamp", 0))
        match_time = datetime.fromtimestamp(timestamp, tz=TZ).strftime("%H:%M")
        msg += f"🏟 {home} vs {away}\n"
        msg += f"   📅 Ligue : {league}\n" if lang == "fr" else f"   📅 League: {league}\n"
        msg += f"   🕐 Heure : {match_time}\n\n"
    if lang == "fr":
        msg += "💡 *Suggestions simples* : Les équipes à domicile ayant gagné hier pourraient être en confiance. Vérifiez les cotes avant de parier."
    else:
        msg += "💡 *Simple suggestions*: Home teams that won yesterday might be confident. Check odds before betting."
    return msg

# ------------------- COMMANDES TELEGRAM -------------------
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Commande /start"""
    if LANGUAGE == "fr":
        text = (
            "👋 Bonjour ! Je suis ton assistant football.\n"
            "Commandes disponibles :\n"
            "/trends - Comparer les tendances des matchs d'hier et d'aujourd'hui (déjà joués)\n"
            f"/upcoming30 - Voir les matchs qui commencent dans les {UPCOMING_MINUTES} prochaines minutes\n"
            "/help - Aide"
        )
    else:
        text = (
            "👋 Hello! I am your football assistant.\n"
            "Available commands:\n"
            "/trends - Compare trends of yesterday and today (already played)\n"
            f"/upcoming30 - See matches starting in the next {UPCOMING_MINUTES} minutes\n"
            "/help - Help"
        )
    await update.message.reply_text(text)

async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Commande /help"""
    await start(update, context)

async def trends(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Commande /trends"""
    now = datetime.now(TZ)
    today_str = now.strftime("%Y-%m-%d")
    yesterday_str = (now - timedelta(days=1)).strftime("%Y-%m-%d")

    await update.message.reply_text("⏳ Analyse des matchs en cours...")

    yesterday_events = get_events_for_date(yesterday_str)
    today_events = get_events_for_date(today_str)

    yesterday_finished = filter_finished_matches(yesterday_events)
    today_finished = filter_finished_matches(today_events)

    if not today_finished:
        await update.message.reply_text("Aucun match terminé aujourd'hui pour le moment.")
        return

    y_trends = compute_trends(yesterday_finished)
    t_trends = compute_trends(today_finished)

    message = format_trends_message(y_trends, t_trends, LANGUAGE)
    await update.message.reply_text(message, parse_mode="Markdown")

async def upcoming30(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Commande /upcoming30"""
    now = datetime.now(TZ)
    today_str = now.strftime("%Y-%m-%d")

    await update.message.reply_text("⏳ Recherche des matchs à venir...")

    events = get_events_for_date(today_str)
    upcoming = filter_upcoming_matches(events, now, UPCOMING_MINUTES, TZ)

    message = format_upcoming_message(upcoming, LANGUAGE, UPCOMING_MINUTES)
    await update.message.reply_text(message, parse_mode="Markdown")

# ------------------- MAIN -------------------
def main():
    """Démarre le bot."""
    if not TELEGRAM_BOT_TOKEN:
        logger.error("Token Telegram manquant. Définissez TELEGRAM_BOT_TOKEN.")
        return

    application = Application.builder().token(TELEGRAM_BOT_TOKEN).build()

    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("help", help_command))
    application.add_handler(CommandHandler("trends", trends))
    application.add_handler(CommandHandler("upcoming30", upcoming30))

    logger.info("Bot démarré...")
    application.run_polling(allowed_updates=Update.ALL_TYPES)

if __name__ == "__main__":
    main()

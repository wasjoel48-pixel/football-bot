#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
Bot Telegram d'analyse de football
Auteur : Assistant
Description : Bot qui analyse les matchs déjà joués aujourd'hui et donne les tendances
par rapport à hier, et liste les matchs à venir dans les 30 prochaines minutes.
Adapté au fuseau horaire de Douala (Afrique/Douala, UTC+1).
API utilisée : TheSportsDB (gratuite, sans clé).
"""

import requests
import logging
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo  # Python 3.9+
# Si Python < 3.9, utiliser pytz : import pytz

from telegram import Update
from telegram.ext import Application, CommandHandler, ContextTypes

# ================= CONFIGURATION =================
TELEGRAM_BOT_TOKEN = "VOTRE_TOKEN_ICI"  # Remplacez par le token de votre bot
API_BASE_URL = "https://www.thesportsdb.com/api/v1/json/3"
TIMEZONE = ZoneInfo("Africa/Douala")  # Fuseau horaire de Douala
# =================================================

# Activer les logs
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO
)
logger = logging.getLogger(__name__)


def get_events_for_date(date_str: str) -> list:
    """
    Récupère tous les événements de football pour une date donnée (format YYYY-MM-DD)
    depuis TheSportsDB.
    """
    url = f"{API_BASE_URL}/eventsday.php?d={date_str}&s=Soccer"
    try:
        response = requests.get(url, timeout=10)
        response.raise_for_status()
        data = response.json()
        return data.get("events", [])
    except Exception as e:
        logger.error(f"Erreur API pour la date {date_str}: {e}")
        return []


def filter_finished_matches(events: list) -> list:
    """
    Filtre les matchs terminés (strStatus == "Match Finished").
    """
    return [ev for ev in events if ev.get("strStatus") == "Match Finished"]


def filter_upcoming_matches(events: list, now: datetime, delta_minutes: int = 30) -> list:
    """
    Filtre les matchs dont le coup d'envoi est entre maintenant et maintenant + delta_minutes.
    """
    upcoming = []
    for ev in events:
        if ev.get("strStatus") != "Not Started":
            continue
        timestamp_str = ev.get("strTimestamp")
        if not timestamp_str:
            continue
        try:
            match_time = datetime.fromtimestamp(int(timestamp_str), tz=TIMEZONE)
        except (ValueError, TypeError):
            continue
        if now <= match_time <= now + timedelta(minutes=delta_minutes):
            upcoming.append(ev)
    return upcoming


def compute_trends(events: list) -> dict:
    """
    Calcule des statistiques simples sur une liste de matchs terminés.
    Retourne un dictionnaire avec : nb_matchs, home_wins, draws, away_wins,
    total_goals, avg_goals, home_goals, away_goals.
    """
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
    home_wins = 0
    draws = 0
    away_wins = 0
    total_goals = 0
    home_goals = 0
    away_goals = 0
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


def format_trends_message(yesterday_trends: dict, today_trends: dict) -> str:
    """
    Formate le message de comparaison des tendances entre hier et aujourd'hui.
    """
    msg = "📊 *Tendances des matchs déjà joués*\n\n"
    msg += f"*Hier* ({yesterday_trends['nb_matchs']} matchs)\n"
    msg += f"🏠 Victoires à domicile : {yesterday_trends['home_wins']}\n"
    msg += f"🤝 Nuls : {yesterday_trends['draws']}\n"
    msg += f"✈️ Victoires à l'extérieur : {yesterday_trends['away_wins']}\n"
    msg += f"⚽ Buts (dom/ext/total) : {yesterday_trends['home_goals']}/{yesterday_trends['away_goals']}/{yesterday_trends['total_goals']}\n"
    msg += f"📈 Moyenne de buts/match : {yesterday_trends['avg_goals']}\n\n"
    msg += f"*Aujourd'hui (déjà joués)* ({today_trends['nb_matchs']} matchs)\n"
    msg += f"🏠 Victoires à domicile : {today_trends['home_wins']}\n"
    msg += f"🤝 Nuls : {today_trends['draws']}\n"
    msg += f"✈️ Victoires à l'extérieur : {today_trends['away_wins']}\n"
    msg += f"⚽ Buts (dom/ext/total) : {today_trends['home_goals']}/{today_trends['away_goals']}/{today_trends['total_goals']}\n"
    msg += f"📈 Moyenne de buts/match : {today_trends['avg_goals']}\n\n"
    # Comparaison rapide
    msg += "🔎 *Comparaison*\n"
    msg += f"• Victoires à domicile : {'⬆️' if today_trends['home_wins'] > yesterday_trends['home_wins'] else '⬇️' if today_trends['home_wins'] < yesterday_trends['home_wins'] else '➡️'} (hier {yesterday_trends['home_wins']} → aujourd'hui {today_trends['home_wins']})\n"
    msg += f"• Nuls : {'⬆️' if today_trends['draws'] > yesterday_trends['draws'] else '⬇️' if today_trends['draws'] < yesterday_trends['draws'] else '➡️'} (hier {yesterday_trends['draws']} → aujourd'hui {today_trends['draws']})\n"
    msg += f"• Victoires à l'extérieur : {'⬆️' if today_trends['away_wins'] > yesterday_trends['away_wins'] else '⬇️' if today_trends['away_wins'] < yesterday_trends['away_wins'] else '➡️'} (hier {yesterday_trends['away_wins']} → aujourd'hui {today_trends['away_wins']})\n"
    msg += f"• Moyenne de buts : {'⬆️' if today_trends['avg_goals'] > yesterday_trends['avg_goals'] else '⬇️' if today_trends['avg_goals'] < yesterday_trends['avg_goals'] else '➡️'} (hier {yesterday_trends['avg_goals']} → aujourd'hui {today_trends['avg_goals']})"
    return msg


def format_upcoming_message(matches: list) -> str:
    """
    Formate le message pour les matchs à venir dans les 30 prochaines minutes.
    """
    if not matches:
        return "Aucun match ne commence dans les 30 prochaines minutes."
    msg = "⏰ *Matchs à venir dans les 30 prochaines minutes* (heure de Douala)\n\n"
    for ev in matches:
        home = ev.get("strHomeTeam", "?")
        away = ev.get("strAwayTeam", "?")
        league = ev.get("strLeague", "?")
        timestamp = int(ev.get("strTimestamp", 0))
        match_time = datetime.fromtimestamp(timestamp, tz=TIMEZONE).strftime("%H:%M")
        msg += f"🏟 {home} vs {away}\n"
        msg += f"   📅 Ligue : {league}\n"
        msg += f"   🕐 Heure : {match_time}\n\n"
    # Petite note "meilleurs choix" basée sur un critère simple : les équipes à domicile
    # ayant gagné hier sont favorisées (mais cela reste une suggestion)
    msg += "💡 *Suggestions simples* : Les équipes à domicile ayant gagné hier pourraient être en confiance. Vérifiez les cotes avant de parier."
    return msg


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Commande /start"""
    await update.message.reply_text(
        "👋 Bonjour ! Je suis ton assistant football.\n"
        "Commandes disponibles :\n"
        "/trends - Comparer les tendances des matchs d'hier et d'aujourd'hui (déjà joués)\n"
        "/upcoming30 - Voir les matchs qui commencent dans les 30 prochaines minutes"
    )


async def trends(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Commande /trends"""
    now = datetime.now(TIMEZONE)
    today_str = now.strftime("%Y-%m-%d")
    yesterday_str = (now - timedelta(days=1)).strftime("%Y-%m-%d")

    await update.message.reply_text("⏳ Analyse des matchs en cours...")

    # Récupération des événements
    yesterday_events = get_events_for_date(yesterday_str)
    today_events = get_events_for_date(today_str)

    # Filtrage des matchs terminés
    yesterday_finished = filter_finished_matches(yesterday_events)
    today_finished = filter_finished_matches(today_events)

    if not today_finished:
        await update.message.reply_text("Aucun match terminé aujourd'hui pour le moment.")
        return

    # Calcul des tendances
    y_trends = compute_trends(yesterday_finished)
    t_trends = compute_trends(today_finished)

    # Envoi du message
    message = format_trends_message(y_trends, t_trends)
    await update.message.reply_text(message, parse_mode="Markdown")


async def upcoming30(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Commande /upcoming30"""
    now = datetime.now(TIMEZONE)
    today_str = now.strftime("%Y-%m-%d")

    await update.message.reply_text("⏳ Recherche des matchs à venir...")

    events = get_events_for_date(today_str)
    upcoming = filter_upcoming_matches(events, now, delta_minutes=30)

    message = format_upcoming_message(upcoming)
    await update.message.reply_text(message, parse_mode="Markdown")


def main():
    """Démarre le bot"""
    if TELEGRAM_BOT_TOKEN == "VOTRE_TOKEN_ICI":
        logger.error("Veuillez remplacer TELEGRAM_BOT_TOKEN par le token de votre bot Telegram.")
        return

    # Création de l'application
    application = Application.builder().token(TELEGRAM_BOT_TOKEN).build()

    # Ajout des handlers
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("trends", trends))
    application.add_handler(CommandHandler("upcoming30", upcoming30))

    # Démarrage du bot
    logger.info("Bot démarré...")
    application.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()

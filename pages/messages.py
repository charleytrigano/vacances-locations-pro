"""
Page Messages - Email (Brevo) + SMS (Brevo) + WhatsApp (wa.me / Twilio)
"""
import streamlit as st
import pandas as pd
from datetime import date, timedelta

try:
    from database.proprietes_repo import fetch_all as _fa_props
    from database.proprietes_repo import fetch_all as fetch_proprietes
except ImportError:
    def _fa_props(): return []
    def fetch_proprietes(): return []

try:
    from services.auth_service import is_unlocked
except ImportError:
    def is_unlocked(x): return True

try:
    from services.reservation_service import load_reservations
except ImportError:
    def load_reservations(): 
        import pandas as pd; return pd.DataFrame()

try:
    from services.messaging_service import (
        send_confirmation, send_checkin_reminder,
        send_checkout_followup, send_payment_reminder,
        send_checkin_sms, send_payment_sms,
    )
except ImportError:
    def send_confirmation(r): return {"ok": False, "error": "Non configuré"}
    def send_checkin_reminder(r): return {"ok": False, "error": "Non configuré"}
    def send_checkout_followup(r): return {"ok": False, "error": "Non configuré"}
    def send_payment_reminder(r): return {"ok": False, "error": "Non configuré"}
    def send_checkin_sms(r): return {"ok": False, "error": "Non configuré"}
    def send_payment_sms(r): return {"ok": False, "error": "Non configuré"}

try:
    from integrations.whatsapp_client import build_wa_link, send_whatsapp
except ImportError:
    def build_wa_link(tel, msg): return None
    def send_whatsapp(tel, msg): return {"ok": False, "error": "Non configuré"}

try:
    from database.supabase_client import is_connected
except ImportError:
    def is_connected(): return False

try:
    import database.reservations_repo as repo
except ImportError:
    repo = None

try:
    from config import BREVO_API_KEY
except ImportError:
    BREVO_API_KEY = ""

try:
    from config import TWILIO_ACCOUNT_SID
except ImportError:
    TWILIO_ACCOUNT_SID = ""

try:
    from database.templates_repo import get_templates
except ImportError:
    def get_templates(**kwargs): return []

try:
    from services.template_service import apply_template, apply_template_texte
except ImportError:
    def apply_template(c, r, **kw): return c
    def apply_template_texte(c, r, **kw): return c

MOMENTS = {
    "confirmation": "✅ Confirmation réservation",
    "j-3":          "📅 Rappel arrivée J-3",
    "arrivee":      "🏠 Jour d'arrivée",
    "depart":       "🧳 Veille départ",
    "post_depart":  "⭐ Post-départ & avis",
    "paiement":     "💳 Rappel paiement",
    "fidelite":     "🎁 Offre fidélité",
    "autre":        "📝 Autre",
}
try:
    from services.template_service import MOMENTS
except ImportError:
    pass

def show():
    st.title("📧 Messages & Notifications")
    df = load_reservations()
    if not df.empty:
        _auth = [p["id"] for p in _fa_props() if not p.get("mot_de_passe") or is_unlocked(p["id"])]
        df = df[df["propriete_id"].isin(_auth)]
    if df.empty:
        st.info("Aucune réservation disponible.")
        return
    # ── Filtre propriété global ───────────────────────────────────────────
    props_all = {p["id"]: p["nom"] for p in _fa_props()}
    props_filtre = {0: "🏠 Toutes les propriétés"}
    props_filtre.update({pid: nom for pid, nom in props_all.items()
                         if not _fa_props() or True})
    # Reconstruire depuis fetch_proprietes
    _all_props = fetch_proprietes()
    props_filtre = {"all": "🏠 Toutes les propriétés"}
    props_filtre.update({str(p["id"]): p["nom"] for p in _all_props
                         if not p.get("mot_de_passe") or is_unlocked(p["id"])})

    prop_filtre_key = st.selectbox(
        "🏠 Propriété",
        options=list(props_filtre.keys()),
        format_func=lambda x: props_filtre[x],
        key="msg_prop_filtre",
        label_visibility="collapsed"
    )
    if prop_filtre_key != "all":
        df = df[df["propriete_id"] == int(prop_filtre_key)]

    st.caption(f"**{len(df)} réservation(s)** pour {props_filtre[prop_filtre_key]}")

    tab_wa, tab_auto, tab_email, tab_sms, tab_histo = st.tabs([
        "💬 WhatsApp", "🤖 Automatique", "✉️ Email", "📱 SMS", "📊 Historique"
    ])
    with tab_wa:    _show_whatsapp(df)
    with tab_auto:  _show_auto(df)
    with tab_email: _show_email_manuel(df)
    with tab_sms:   _show_sms_manuel(df)
    with tab_histo: _show_historique(df)

# ─────────────────────────────────────────────────────────────────────────────
# WHATSAPP
# ─────────────────────────────────────────────────────────────────────────────
def _show_whatsapp(df: pd.DataFrame):
    st.subheader("💬 WhatsApp")
    twilio_ok = bool(TWILIO_ACCOUNT_SID)
    col_brevo, col_twilio = st.columns(2)
    with col_brevo:
        st.info("🔗 **Mode lien wa.me** — toujours disponible", icon="✅")
    with col_twilio:
        if twilio_ok:
            st.success("🤖 **Twilio configuré** — envoi automatique activé", icon="✅")
        else:
            st.warning("🤖 **Twilio non configuré** — envoi manuel uniquement", icon="⚠️")
    st.divider()

    search_wa = st.text_input("🔎 Rechercher un client", placeholder="Tapez un nom...", key="wa_search")
    df_sel = df.sort_values("date_arrivee", ascending=False)
    if search_wa:
        df_sel = df_sel[df_sel["nom_client"].str.contains(search_wa, case=False, na=False)]
    options = {
        row["id"]: (
            f"{row['nom_client']} "
            f"({'📱 ' + str(row.get('telephone','')) if row.get('telephone') else '❌ sans tél'})"
            f"  |  {row['plateforme']}  |  "
            f"{row['date_arrivee'].strftime('%d/%m/%Y') if hasattr(row['date_arrivee'], 'strftime') else str(row['date_arrivee'])[:10]}"
        )
        for _, row in df_sel.iterrows()
    }
    if not options:
        st.info("Aucune réservation trouvée.")
        return

    col1, col2 = st.columns([3, 2])
    with col1:
        selected_id = st.selectbox("Réservation", list(options.keys()),
                                    format_func=lambda x: options[x], key="wa_sel")
    if selected_id is None:
        with col2:
            st.selectbox("Modèle", [], key="wa_tpl_empty")
        return
    row = df[df["id"] == selected_id].iloc[0].to_dict()
    telephone = str(row.get("telephone", "") or "")
    with col2:
        tpls_wa = get_templates(canal="whatsapp")
        tpl_options_wa = {0: "✏️ Message personnalisé"}
        tpl_options_wa.update({
            t["id"]: f"{t['nom']}  ({MOMENTS.get(t.get('moment',''), '')})"
            for t in tpls_wa
        })
        tpl_id_wa = st.selectbox("Modèle", list(tpl_options_wa.keys()),
                                  format_func=lambda x: tpl_options_wa[x], key="wa_tpl")

    props_map  = {p["id"]: p for p in fetch_proprietes()}
    prop_id    = int(row.get("propriete_id", 0) or 0)
    prop_data  = props_map.get(prop_id, {})
    prop_nom   = prop_data.get("nom", "")
    ville      = prop_data.get("adresse", "") or prop_data.get("ville", "")
    signataire = prop_data.get("signataire", "") or ""
    pays_client = str(row.get("pays", "") or "")

    if tpl_id_wa == 0:
        message = st.text_area("Message WhatsApp",
                                value=f"Bonjour {row.get('nom_client','').split()[0]} 👋\n\n",
                                height=150, key="wa_custom_msg")
    else:
        tpl_obj = next((t for t in tpls_wa if t["id"] == tpl_id_wa), None)
        message = ""
        if tpl_obj:
            import os as _os
            _app_url = st.secrets.get("APP_URL", _os.environ.get("APP_URL", ""))
            _res_id  = str(row.get("res_id", row.get("id", "")))
            import hashlib as _hl
            _token  = _hl.md5(f"{_res_id}{_app_url}".encode()).hexdigest()[:16]
            _lien_q = f"{_app_url}/?token={_token}" if _app_url and _res_id else ""
            # Message HTML pour aperçu (avec image drapeau)
            message_html = apply_template(tpl_obj["contenu"], row,
                                          propriete_nom=prop_nom, ville=ville,
                                          signataire=signataire,
                                          lien_questionnaire=_lien_q)
            # Message texte pour WhatsApp (avec code pays [NL])
            message = apply_template_texte(tpl_obj["contenu"], row,
                                           propriete_nom=prop_nom, ville=ville,
                                           signataire=signataire,
                                           lien_questionnaire=_lien_q)

        # ── Traduction via session_state (uniquement si traduit) ─────
        _trad_key = f"wa_msg_traduit_{selected_id}_{tpl_id_wa}"
        # NE PAS stocker le message original — uniquement la version traduite

        try:
            from services.traduction_service import get_langue_from_pays
            _lg = get_langue_from_pays(pays_client)
        except Exception:
            _lg = None

        if _lg and message:
            _, _nom_lg = _lg
            _c1, _c2, _c3 = st.columns([3, 1, 1])
            with _c1:
                st.info(f"🌍 **{pays_client}** — traduction **{_nom_lg}** disponible")
            with _c2:
                _bilingue = st.checkbox("Bilingue", value=True, key=f"wa_bilingue_{selected_id}")
            with _c3:
                if st.button(f"🌐 Traduire", key=f"btn_trad_wa_{selected_id}"):
                    with st.spinner(f"Traduction en {_nom_lg}..."):
                        try:
                            from services.traduction_service import traduire_message
                            _r = traduire_message(message, pays_client, bilingue=_bilingue)
                            if _r["traduit"]:
                                st.session_state[_trad_key] = _r["message_final"]
                                st.success(f"✅ Traduit !")
                            else:
                                st.error(f"❌ {_r.get('erreur','Erreur')}")
                        except Exception as _e:
                            st.error(f"❌ {_e}")

        # Utiliser la version traduite si disponible, sinon le message original
        if _trad_key in st.session_state and st.session_state[_trad_key]:
            message = st.session_state[_trad_key]
        # Aperçu en texte brut via composant natif Streamlit (garanti lisible,
        # même rendu que "Message personnalisé" qui fonctionne déjà bien)
        _apercu_html = message_html if "message_html" in dir() else message
        if _trad_key in st.session_state and st.session_state[_trad_key]:
            _apercu_html = st.session_state[_trad_key]
        import re as _re_strip
        _apercu_texte = _re_strip.sub(r"<[^>]+>", "", _apercu_html)
        st.text_area("Aperçu :", value=_apercu_texte, height=220, disabled=True, key="wa_apercu_readonly")

    tel_input = st.text_input("Numéro WhatsApp", value=telephone, placeholder="+33 6 12 34 56 78")
    st.markdown("---")
    col_a, col_b = st.columns(2)
    with col_a:
        if tel_input:
            link = build_wa_link(tel_input, message)
            if link:
                st.link_button("💬 Ouvrir dans WhatsApp", url=link,
                                type="primary", use_container_width=True)
            else:
                st.error("Numéro invalide")
        else:
            st.button("💬 Ouvrir dans WhatsApp", disabled=True, use_container_width=True)
    with col_b:
        if twilio_ok:
            if st.button("🤖 Envoyer automatiquement (Twilio)", use_container_width=True):
                if not tel_input:
                    st.error("Numéro manquant")
                else:
                    result = send_whatsapp(tel_input, message)
                    if result.get("ok"):
                        st.success(f"✅ Envoyé ! SID: {result.get('sid','')}")
                    else:
                        st.error(f"❌ {result.get('error')}")
        else:
            st.button("🤖 Envoyer (Twilio)", disabled=True, use_container_width=True,
                      help="Configurez Twilio dans les Secrets")

    st.divider()
    st.subheader("📨 Envoi en masse")
    today = pd.Timestamp(date.today())
    in_7  = today + timedelta(days=7)
    preset = st.selectbox("Cibler", [
        "Arrivées dans 7 jours",
        "Paiements en attente + arrivée dans 14 jours",
        "Tous les séjours à venir",
    ], key="wa_bulk_preset")
    if preset == "Arrivées dans 7 jours":
        df_bulk = df[(df["date_arrivee"] >= today) & (df["date_arrivee"] <= in_7) & df["telephone"].notna()]
    elif preset == "Paiements en attente + arrivée dans 14 jours":
        df_bulk = df[(df["paye"] == False) & (df["date_arrivee"] >= today) &
                     (df["date_arrivee"] <= today + timedelta(days=14)) & df["telephone"].notna()]
    else:
        df_bulk = df[(df["date_arrivee"] >= today) & df["telephone"].notna()]
    tpls_bulk = get_templates(canal="whatsapp")
    tpl_bulk_opts = {t["id"]: t["nom"] for t in tpls_bulk}
    st.markdown(f"**{len(df_bulk)} contact(s)** — choisir le template :")
    tpl_bulk_id = st.selectbox("Template envoi masse", list(tpl_bulk_opts.keys()),
                                format_func=lambda x: tpl_bulk_opts[x],
                                key="bulk_tpl") if tpl_bulk_opts else None
    if not df_bulk.empty:
        st.dataframe(df_bulk[["nom_client", "telephone", "date_arrivee", "plateforme"]].head(10),
                     use_container_width=True, hide_index=True)
        if twilio_ok and tpl_bulk_id:
            if st.button(f"🤖 Envoyer à tous ({len(df_bulk)}) via Twilio", type="primary"):
                tpl_bulk_obj = next((t for t in tpls_bulk if t["id"] == tpl_bulk_id), None)
                ok_cnt, errors = 0, []
                prog = st.progress(0)
                for i, (_, r) in enumerate(df_bulk.iterrows()):
                    if tpl_bulk_obj:
                        _pm = props_map.get(int(r.get("propriete_id", 0) or 0), {})
                        msg = apply_template(tpl_bulk_obj["contenu"], r.to_dict(),
                                             propriete_nom=_pm.get("nom",""),
                                             signataire=_pm.get("signataire",""))
                    else:
                        msg = f"Bonjour {r.get('nom_client','')}"
                    res = send_whatsapp(str(r.get("telephone", "")), msg)
                    if res.get("ok"): ok_cnt += 1
                    else: errors.append(f"{r['nom_client']}: {res.get('error')}")
                    prog.progress((i + 1) / len(df_bulk))
                st.success(f"✅ {ok_cnt} message(s) envoyé(s)")
                for e in errors[:5]: st.error(f"❌ {e}")
        elif tpl_bulk_id:
            if st.button(f"💬 Générer les liens ({len(df_bulk)})", type="primary"):
                tpl_bulk_obj = next((t for t in tpls_bulk if t["id"] == tpl_bulk_id), None)
                for _, r in df_bulk.iterrows():
                    if tpl_bulk_obj:
                        _pm = props_map.get(int(r.get("propriete_id", 0) or 0), {})
                        msg = apply_template(tpl_bulk_obj["contenu"], r.to_dict(),
                                             propriete_nom=_pm.get("nom",""),
                                             signataire=_pm.get("signataire",""))
                    else:
                        msg = ""
                    lnk = build_wa_link(str(r.get("telephone", "")), msg)
                    if lnk:
                        st.markdown(f"- [{r.get('nom_client','')}]({lnk})")

# ─────────────────────────────────────────────────────────────────────────────
# AUTO
# ─────────────────────────────────────────────────────────────────────────────
def _show_auto(df: pd.DataFrame):
    st.subheader("🤖 Envois automatiques suggérés")
    today = pd.Timestamp(date.today())
    j2    = today + timedelta(days=2)
    hier  = today - timedelta(days=1)
    rappels   = df[(df["date_arrivee"].dt.date == j2.date()) &
                   (df["sms_envoye"] == False) & df["email"].notna()]
    post_dep  = df[(df["date_depart"].dt.date == hier.date()) &
                   (df["post_depart_envoye"] == False) & df["email"].notna()]
    paiements = df[(df["paye"] == False) & (df["date_arrivee"] >= today) &
                   (df["date_arrivee"] <= today + timedelta(days=7)) & df["email"].notna()]
    _section_auto(rappels,   "🔔 Rappels arrivée (J-2)",          "Envoyer rappels arrivée",
                  send_checkin_reminder,  "sms_envoye",         "checkin")
    st.divider()
    _section_auto(post_dep,  "🙏 Messages post-départ (J+1)",     "Envoyer post-départ",
                  send_checkout_followup, "post_depart_envoye", "postdepart")
    st.divider()
    _section_auto(paiements, "💳 Rappels paiement (arrivée <7j)", "Envoyer rappels paiement",
                  send_payment_reminder,  None,                  "paiement")

def _section_auto(df_sub, titre, btn_label, fn_send, flag_col, key_suffix):
    st.markdown(f"**{titre}**")
    if df_sub.empty:
        st.success("✅ Aucun envoi nécessaire.")
        return
    cols = ["nom_client", "email", "date_arrivee", "plateforme"]
    st.dataframe(df_sub[[c for c in cols if c in df_sub.columns]],
                 use_container_width=True, hide_index=True)
    if st.button(f"📤 {btn_label} ({len(df_sub)})", key=f"btn_{key_suffix}", type="primary"):
        ok, errors = 0, []
        for _, row in df_sub.iterrows():
            result = fn_send(row.to_dict())
            if result.get("ok"):
                ok += 1
                if flag_col and is_connected():
                    try: repo.update_reservation(int(row["id"]), {flag_col: True})
                    except: pass
            else:
                errors.append(f"{row['nom_client']}: {result.get('error')}")
        if ok: st.success(f"✅ {ok} message(s) envoyé(s)")
        for e in errors: st.error(f"❌ {e}")

# ─────────────────────────────────────────────────────────────────────────────
# EMAIL MANUEL
# ─────────────────────────────────────────────────────────────────────────────
def _show_email_manuel(df: pd.DataFrame):
    st.subheader("✉️ Envoyer un email")
    if not BREVO_API_KEY:
        st.error("⛔ BREVO_API_KEY non configurée dans les Secrets Streamlit Cloud.")
        return
    search_email = st.text_input("🔎 Rechercher un client", placeholder="Tapez un nom...", key="email_search")
    df_email = df.sort_values("date_arrivee", ascending=False)
    if search_email:
        df_email = df_email[df_email["nom_client"].str.contains(search_email, case=False, na=False)]
    options = {row["id"]: f"{row['nom_client']} ({row.get('email','sans email')})"
               for _, row in df_email.iterrows()}
    if not options:
        st.info("Aucune réservation trouvée.")
        return

    if not search_email:
        st.info("🔎 Tapez un nom pour rechercher un client.")
        return

    selected_id = st.selectbox("Réservation", list(options.keys()),
                                format_func=lambda x: options[x], key="email_sel")
    row = df[df["id"] == selected_id].iloc[0].to_dict()
    pays_client_e = str(row.get("pays", "") or "")

    col1, col2 = st.columns(2)
    with col1:
        tpls_email = get_templates(canal="whatsapp")
        tpl_options_email = {"__custom__": "✏️ Personnalisé"}
        tpl_options_email.update({
            t["id"]: f"{t['nom']}  ({MOMENTS.get(t.get('moment',''), '')})"
            for t in tpls_email
        })
        tpl_id_email = st.selectbox("Template", list(tpl_options_email.keys()),
                                     format_func=lambda x: tpl_options_email[x], key="email_tpl")
    with col2:
        email_dest = st.text_input("Email", value=str(row.get("email", "") or ""))

    props_e    = {p["id"]: p for p in fetch_proprietes()}
    pid_e      = int(row.get("propriete_id") or 0)
    prop_e     = props_e.get(pid_e, {})
    prop_nom_e = prop_e.get("nom", "")
    ville_e    = prop_e.get("ville", "") or prop_e.get("adresse", "")
    sign_e     = prop_e.get("signataire", "") or ""

    if tpl_id_email == "__custom__":
        sujet         = st.text_input("Sujet", key="email_sujet_custom")
        message_email = st.text_area("Message", height=200, key="email_corps_custom")
    else:
        tpl_obj_e = next((t for t in tpls_email if t["id"] == tpl_id_email), None)
        message_email = ""
        sujet = ""
        if tpl_obj_e:
            message_email = apply_template(tpl_obj_e["contenu"], row,
                                           propriete_nom=prop_nom_e,
                                           ville=ville_e, signataire=sign_e)
            sujet = tpl_obj_e.get("nom", "Message")

        # ── Traduction via session_state ──────────────────────────────
        _trad_key_e = f"email_msg_traduit_{selected_id}_{tpl_id_email}"
        # NE PAS stocker le message original — uniquement la version traduite

        try:
            from services.traduction_service import get_langue_from_pays
            _lg_e = get_langue_from_pays(pays_client_e)
        except Exception:
            _lg_e = None

        if _lg_e and message_email:
            _, _nom_lg_e = _lg_e
            _ec1, _ec2, _ec3 = st.columns([3, 1, 1])
            with _ec1:
                st.info(f"🌍 **{pays_client_e}** — traduction **{_nom_lg_e}** disponible")
            with _ec2:
                _bilingue_e = st.checkbox("Bilingue", value=True, key=f"email_bilingue_{selected_id}")
            with _ec3:
                if st.button(f"🌐 Traduire", key=f"btn_trad_email_{selected_id}"):
                    with st.spinner(f"Traduction en {_nom_lg_e}..."):
                        try:
                            from services.traduction_service import traduire_message
                            _r_e = traduire_message(message_email, pays_client_e, bilingue=_bilingue_e)
                            if _r_e["traduit"]:
                                st.session_state[_trad_key_e] = _r_e["message_final"]
                                st.success("✅ Traduit !")
                            else:
                                st.error(f"❌ {_r_e.get('erreur','Erreur')}")
                        except Exception as _e2:
                            st.error(f"❌ {_e2}")

        if _trad_key_e in st.session_state and st.session_state[_trad_key_e]:
            message_email = st.session_state[_trad_key_e]
        st.text_area("Aperçu du message", value=message_email, height=200,
                     disabled=True, key="email_preview")

    if st.button("📤 Envoyer l'email", type="primary", use_container_width=True):
        if not email_dest:
            st.error("Email manquant."); return
        if not message_email:
            st.error("Message vide."); return
        html_lines = "<br>".join(message_email.split("\n"))
        html_body = f"""<div style="font-family:Arial,sans-serif;max-width:600px;margin:auto;border:1px solid #e0e0e0;border-radius:8px;overflow:hidden"><div style="background:#1565C0;padding:20px;text-align:center"><h2 style="color:white;margin:0">🏖️ {prop_nom_e or 'Vacances-Locations'}</h2></div><div style="padding:24px;line-height:1.7">{html_lines}</div><div style="background:#f5f5f5;padding:12px;text-align:center;font-size:12px;color:#757575">Vacances-Locations PRO — Gestion locative</div></div>"""
        from integrations.brevo_client import send_email as _send_email
        result = _send_email(email_dest, row.get("nom_client", ""), sujet, html_body)
        if result.get("ok"):
            st.success(f"✅ Email envoyé à {email_dest}")
        else:
            st.error(f"❌ {result.get('error')}")

# ─────────────────────────────────────────────────────────────────────────────
# SMS MANUEL
# ─────────────────────────────────────────────────────────────────────────────
def _show_sms_manuel(df: pd.DataFrame):
    st.subheader("📱 Envoyer un SMS")
    st.caption("Le SMS partira depuis votre numéro personnel via l'app SMS de votre téléphone.")

    df_tel = df[df["telephone"].notna()]
    if df_tel.empty:
        st.warning("Aucune réservation avec téléphone.")
        return

    # ── Recherche + Sélection réservation ────────────────────────────────
    search_sms = st.text_input("🔎 Rechercher un client", placeholder="Tapez un nom...", key="sms_search")
    df_tel_filtre = df_tel.sort_values("date_arrivee", ascending=False)
    if search_sms:
        df_tel_filtre = df_tel_filtre[df_tel_filtre["nom_client"].str.contains(search_sms, case=False, na=False)]

    if not search_sms:
        st.info("🔎 Tapez un nom pour rechercher un client.")
        return

    if not search_sms:
        st.info("Tapez un nom pour rechercher un client.")
        return

    if df_tel_filtre.empty:
        st.info("Aucun client trouvé.")
        return

    options = {
        row["id"]: (
            f"{row['nom_client']} — "
            f"{row['plateforme']} — "
            f"{row['date_arrivee'].strftime('%d/%m/%Y') if hasattr(row['date_arrivee'], 'strftime') else str(row['date_arrivee'])[:10]} — "
            f"📱 {row.get('telephone','')}"
        )
        for _, row in df_tel_filtre.iterrows()
    }
    selected_id = st.selectbox("Réservation", list(options.keys()),
                                format_func=lambda x: options[x], key="sms_sel")
    row = df[df["id"] == selected_id].iloc[0].to_dict()
    tel = str(row.get("telephone", "") or "").replace(" ","").replace("-","")

    # ── Sélection template WhatsApp ───────────────────────────────────────
    tpls_sms = get_templates(canal="whatsapp")  # Utilise les templates WhatsApp
    tpl_options = {"__perso__": "✏️ Message personnalisé"}
    tpl_options.update({
        t["id"]: f"{t['nom']}  ({MOMENTS.get(t.get('moment',''), '')})"
        for t in tpls_sms
    })

    # Propriété pour appliquer le template
    props_map = {p["id"]: p for p in fetch_proprietes()}
    prop_id   = int(row.get("propriete_id", 0) or 0)
    prop_data = props_map.get(prop_id, {})
    prop_nom  = prop_data.get("nom", "")
    ville     = prop_data.get("adresse", "") or prop_data.get("ville", "")
    signataire = prop_data.get("signataire", "") or ""

    col1, col2 = st.columns([3, 1])
    with col1:
        tpl_id = st.selectbox("Template message", list(tpl_options.keys()),
                               format_func=lambda x: tpl_options[x], key="sms_tpl")
    with col2:
        tel_input = st.text_input("Téléphone", value=tel, key="sms_tel")

    # ── Générer le message ────────────────────────────────────────────────
    if tpl_id == "__perso__":
        msg = st.text_area("Message", height=150, key="sms_custom",
                            placeholder="Tapez votre message...")
    else:
        tpl_obj = next((t for t in tpls_sms if t["id"] == tpl_id), None)
        if tpl_obj:
            msg = apply_template(tpl_obj["contenu"], row,
                                  propriete_nom=prop_nom, ville=ville,
                                  signataire=signataire)
        else:
            msg = ""

        # Traduction automatique si pays détecté
        pays_client = str(row.get("pays", "") or "")
        try:
            from services.traduction_service import get_langue_from_pays
            _lg = get_langue_from_pays(pays_client)
        except Exception:
            _lg = None
        if _lg and msg:
            _, _nom_lg = _lg
            _c1, _c2, _c3 = st.columns([3, 1, 1])
            with _c1:
                st.info(f"🌍 **{pays_client}** — traduction **{_nom_lg}** disponible")
            with _c2:
                _bilingue = st.checkbox("Bilingue", value=True, key=f"sms_bilingue_{selected_id}")
            with _c3:
                if st.button(f"🌐 Traduire", key=f"btn_trad_sms_{selected_id}"):
                    with st.spinner(f"Traduction..."):
                        try:
                            from services.traduction_service import traduire_message
                            _r = traduire_message(msg, pays_client, bilingue=_bilingue)
                            if _r["traduit"]:
                                msg = _r["message_final"]
                                st.success("✅ Traduit !")
                        except Exception as _e:
                            st.error(f"❌ {_e}")

        st.text_area("Aperçu du message", value=msg, height=200,
                      disabled=True, key="sms_preview")

        nb = len(msg)
        nb_sms = max(1, (nb + 159) // 160)
        color = "#4CAF50" if nb <= 160 else "#FF9800" if nb <= 320 else "#F44336"
        st.markdown(f"<small style='color:{color}'>{nb} caractères — {nb_sms} SMS</small>",
                    unsafe_allow_html=True)

    # ── Bouton SMS natif ──────────────────────────────────────────────────
    if msg and tel_input:
        import urllib.parse as _up_sms
        _tel_clean = tel_input.replace(" ","").replace("-","")
        _sms_url = f"sms:{_tel_clean}?body={_up_sms.quote(msg)}"
        st.markdown(
            f"<a href='{_sms_url}'>"
            f"<div style='background:#1565C0;color:white;text-align:center;"
            f"padding:14px;border-radius:8px;font-weight:bold;font-size:16px;"
            f"margin:12px 0'>"
            f"📱 Ouvrir dans l'app SMS</div></a>",
            unsafe_allow_html=True
        )
        st.caption(f"📤 Depuis votre téléphone → {tel_input}")
    else:
        st.button("📱 Ouvrir dans l'app SMS", disabled=True, use_container_width=True)

# ─────────────────────────────────────────────────────────────────────────────
# HISTORIQUE
# ─────────────────────────────────────────────────────────────────────────────
def _show_historique(df: pd.DataFrame):
    st.subheader("📊 Historique des envois")
    cols = ["nom_client", "email", "telephone", "date_arrivee", "sms_envoye", "post_depart_envoye", "plateforme"]
    st.dataframe(
        df[[c for c in cols if c in df.columns]].sort_values("date_arrivee", ascending=False),
        use_container_width=True, hide_index=True,
        column_config={
            "sms_envoye":         st.column_config.CheckboxColumn("Email arrivée envoyé"),
            "post_depart_envoye": st.column_config.CheckboxColumn("Post-départ envoyé"),
        }
    )
    c1, c2, c3 = st.columns(3)
    c1.metric("📧 Rappels arrivée", int(df["sms_envoye"].sum()) if "sms_envoye" in df.columns else 0)
    c2.metric("🙏 Post-départ",     int(df["post_depart_envoye"].sum()) if "post_depart_envoye" in df.columns else 0)
    c3.metric("📋 Total",           len(df))

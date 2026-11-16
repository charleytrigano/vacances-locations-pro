import streamlit as st
import pandas as pd
import plotly.express as px
from services.reservation_service import load_reservations
from services.analytics_service import compute_kpis, compute_monthly
from services.alert_service import upcoming_arrivals, unpaid_reservations
from database.supabase_client import is_connected, get_supabase
from services.proprietes_service import get_proprietes_dict, filter_df, get_propriete_selectionnee


def _show_admin_overview():
    """Vue globale multi-propriétés pour l'admin."""
    from database.proprietes_repo import fetch_all as _fa
    from database.supabase_client import get_supabase as _gsb
    from datetime import date, timedelta
    import pandas as pd

    st.title("📊 Vue d'ensemble — Toutes les propriétés")

    try:
        sb = _gsb()
        if sb is None:
            return

        # Charger toutes les réservations
        result = sb.table("reservations").select("*").neq("plateforme", "Fermeture").execute()
        all_resas = result.data or []
        if not all_resas:
            st.info("Aucune réservation trouvée.")
            return

        df = pd.DataFrame(all_resas)
        df["date_arrivee"] = pd.to_datetime(df["date_arrivee"], errors="coerce")
        df["date_depart"] = pd.to_datetime(df["date_depart"], errors="coerce")
        df["prix_net"] = pd.to_numeric(df.get("prix_net", 0), errors="coerce").fillna(0)
        df["prix_brut"] = pd.to_numeric(df.get("prix_brut", 0), errors="coerce").fillna(0)
        df["nuitees"] = pd.to_numeric(df.get("nuitees", 0), errors="coerce").fillna(0)
        df["paye"] = df.get("paye", False).fillna(False)

        # ── FIX : force_refresh=True pour vider le cache stale ────────────
        props = {p["id"]: p["nom"] for p in _fa(force_refresh=True)}
        df["prop_nom"] = df["propriete_id"].map(props).fillna("?")

        # Filtre année
        annees_dispo = sorted(df["date_arrivee"].dt.year.dropna().unique().tolist(), reverse=True)
        if not annees_dispo:
            st.info("Pas de données exploitables.")
            return
        annee_sel = st.selectbox("Année", annees_dispo, key="admin_ov_annee")
        df_y = df[df["date_arrivee"].dt.year == annee_sel]

        # ── KPIs globaux ──────────────────────────────────────────────────
        ca_total = df_y["prix_net"].sum()
        nuits_tot = int(df_y["nuitees"].sum())
        nb_resas = len(df_y)
        impaye = df_y[df_y["paye"] == False]["prix_net"].sum()

        k1, k2, k3, k4 = st.columns(4)
        k1.metric("💰 CA Net total", f"{ca_total:,.0f} €")
        k2.metric("📅 Réservations", nb_resas)
        k3.metric("🌙 Nuits totales", nuits_tot)
        k4.metric("⚠️ Impayés", f"{impaye:,.0f} €",
                  delta=f"-{impaye:,.0f} €" if impaye > 0 else None,
                  delta_color="inverse")

        st.markdown("")

        # ── Tableau comparatif par propriété ──────────────────────────────
        st.markdown("#### 🏠 Comparatif par propriété")
        rows = []
        for pid, pnom in sorted(props.items()):
            df_p = df_y[df_y["propriete_id"] == pid]
            if df_p.empty:
                continue
            # ── FIX : taux calculé sur l'année sélectionnée uniquement ────
            nuits_p = int(df_p["nuitees"].sum())
            taux = min(100.0, nuits_p / 365 * 100)
            rows.append({
                "Propriété": pnom,
                "Réservations": len(df_p),
                "CA Net (€)": f"{df_p['prix_net'].sum():,.0f}",
                "Nuits": nuits_p,
                "Taux occ.": f"{taux:.1f}%",
                "Impayés (€)": f"{df_p[df_p['paye'] == False]['prix_net'].sum():,.0f}",
            })

        if rows:
            st.dataframe(pd.DataFrame(rows), use_container_width=True, hide_index=True)

        # ── Arrivées et départs ──────────────────────────────────────────
        today = date.today()
        demain = today + timedelta(days=1)

        arr_demain = df[df["date_arrivee"].dt.date == demain]
        dep_auj = df[df["date_depart"].dt.date == today]

        col_a, col_d = st.columns(2)
        with col_a:
            st.markdown(f"#### 🏠 Arrivées demain ({len(arr_demain)})")
            if not arr_demain.empty:
                for _, r in arr_demain.iterrows():
                    st.markdown(f"- **{r.get('nom_client','?')}** — {r.get('prop_nom','?')} — {r.get('plateforme','?')}")
            else:
                st.caption("Aucune arrivée demain")

        with col_d:
            st.markdown(f"#### 🚪 Départs aujourd'hui ({len(dep_auj)})")
            if not dep_auj.empty:
                for _, r in dep_auj.iterrows():
                    st.markdown(f"- **{r.get('nom_client','?')}** — {r.get('prop_nom','?')}")
            else:
                st.caption("Aucun départ aujourd'hui")

        # ── Prochaines réservations (30 jours) ────────────────────────────
        st.markdown("#### 📅 Prochaines réservations (30 jours)")
        df_futur = df[
            (df["date_arrivee"].dt.date >= today) &
            (df["date_arrivee"].dt.date <= today + timedelta(days=30))
        ].sort_values("date_arrivee")

        if not df_futur.empty:
            df_show = df_futur[["prop_nom", "nom_client", "date_arrivee", "date_depart",
                                "nuitees", "prix_net", "plateforme", "paye"]].copy()
            df_show["date_arrivee"] = df_show["date_arrivee"].dt.strftime("%d/%m/%Y")
            df_show["date_depart"] = df_show["date_depart"].dt.strftime("%d/%m/%Y")
            df_show["prix_net"] = df_show["prix_net"].apply(lambda x: f"{x:,.0f} €")
            df_show["paye"] = df_show["paye"].apply(lambda x: "✅" if x else "❌")
            st.dataframe(df_show.rename(columns={
                "prop_nom": "Propriété", "nom_client": "Client",
                "date_arrivee": "Arrivée", "date_depart": "Départ",
                "nuitees": "Nuits", "prix_net": "CA Net", "plateforme": "Plateforme", "paye": "Payé"
            }), use_container_width=True, hide_index=True)
        else:
            st.info("Aucune réservation dans les 30 prochains jours.")

    except Exception as e:
        st.error(f"Erreur vue admin : {e}")


def show():
    # ── Bandeau arrivées demain ────────────────────────────────────────────
    try:
        from datetime import date, timedelta
        _demain = date.today() + timedelta(days=1)
        _df_all = load_reservations()
        if not _df_all.empty:
            _df_all["date_arrivee"] = pd.to_datetime(_df_all["date_arrivee"])
            _arr = _df_all[
                (_df_all["date_arrivee"].dt.date == _demain) &
                (_df_all["plateforme"] != "Fermeture")
            ]
            if not _arr.empty:
                _lignes = []
                for _, _r in _arr.iterrows():
                    _tel = str(_r.get("telephone", "") or "")
                    _lignes.append(
                        f"<b>{_r.get('nom_client','?')}</b> — "
                        f"{_r.get('plateforme','?')} — "
                        f"📱 {_tel if _tel else 'pas de tél'}"
                    )
                st.markdown(
                    f"<div style='background:#1B5E20;border-left:5px solid #69F0AE;"
                    f"padding:12px 18px;border-radius:0 8px 8px 0;margin-bottom:16px'>"
                    f"<b style='color:#69F0AE;font-size:15px'>🏠 Arrivée(s) demain "
                    f"({_demain.strftime('%d/%m/%Y')}) :</b><br>"
                    f"<span style='color:#FFFFFF'>{'<br>'.join(_lignes)}</span>"
                    f"</div>",
                    unsafe_allow_html=True
                )
    except Exception:
        pass

    _is_admin = st.session_state.get("is_admin", False)

    # ── Vue multi-propriétés pour l'admin ─────────────────────────────────
    if _is_admin:
        _show_admin_overview()
        st.divider()

    st.title("📊 Dashboard")

    if is_connected():
        st.success("🟢 Connecté à Supabase", icon="✅")
    else:
        st.warning("🟡 Mode hors ligne — données CSV locales", icon="⚠️")

    # ── Diagnostic table vide ─────────────────────────────────────────────
    if is_connected():
        try:
            sb = get_supabase()
            count = sb.table("reservations").select("id", count="exact").execute()
            nb = count.count if hasattr(count, "count") else len(count.data)
            if nb == 0:
                st.warning("⚠️ **La table Supabase est vide.**")
                st.info("Allez dans 📋 Réservations → 📤 Import CSV pour importer vos données.")
                return
        except Exception as e:
            st.error(f"Erreur vérification table : {e}")
            return

    df_all = load_reservations()
    if df_all.empty:
        st.info("Aucune réservation chargée.")
        return

    # ── Filtre propriété ──────────────────────────────────────────────────
    prop_choix = get_propriete_selectionnee()
    # ── FIX : force_refresh=True pour vider le cache stale ────────────────
    props = get_proprietes_dict(force_refresh=True)

    col_info, col_annee, _ = st.columns([3, 2, 3])
    with col_info:
        if prop_choix != 0:
            st.info(f"🏠 {props.get(prop_choix, f'Propriété {prop_choix}')}")
        else:
            st.info(f"🏠 Toutes les propriétés ({len(props)})")
    with col_annee:
        annees = sorted(df_all["annee"].dropna().unique().tolist(), reverse=True)
        annee_choix = st.selectbox("📆 Année", ["Toutes"] + annees, key="dash_annee")

    # Appliquer filtres
    df = filter_df(df_all, prop_choix)
    if annee_choix != "Toutes":
        df = df[df["annee"] == int(annee_choix)]

    if df.empty:
        st.info("Aucune réservation pour ce filtre.")
        return

    kpis = compute_kpis(df)

    # ── Calcul Fermeture ──────────────────────────────────────────────────
    df_c = df.copy()
    df_c["date_arrivee"] = pd.to_datetime(df_c["date_arrivee"])
    df_c["date_depart"] = pd.to_datetime(df_c["date_depart"])
    mask_ferm = df_c["plateforme"] == "Fermeture"
    df_ferm = df_c[mask_ferm]
    df_reel = df_c[~mask_ferm]

    def _n(d):
        if d.empty:
            return 0
        n = d["nuitees"].copy() if "nuitees" in d.columns else pd.Series(dtype=float)
        if n.empty:
            n = pd.Series([0] * len(d))
        mask0 = n.isna() | (n == 0)
        if mask0.any():
            n.loc[mask0] = (d.loc[mask0, "date_depart"] - d.loc[mask0, "date_arrivee"]).dt.days
        return int(n.fillna(0).sum())

    nuits_fermeture = _n(df_ferm)
    nuits_louees = _n(df_reel)
    ca_net_reel = float(df_reel["prix_net"].sum()) if not df_reel.empty else 0
    revenu_nuit = round(ca_net_reel / nuits_louees) if nuits_louees > 0 else 0
    label_nuits = f"{nuits_louees} (+{nuits_fermeture}🔒)" if nuits_fermeture else str(nuits_louees)

    # ── FIX : plafonner le taux d'occupation à 100% ──────────────────────
    taux_brut = kpis.get('taux_occupation', 0)
    taux_corrige = min(100.0, float(taux_brut)) if taux_brut else 0

    # ── KPIs ──────────────────────────────────────────────────────────────
    c1, c2, c3, c4, c5 = st.columns(5)
    c1.metric("💰 CA Brut", f"{kpis['ca_brut']:,.0f} €")
    c2.metric("💵 CA Net", f"{kpis['ca_net']:,.0f} €")
    c3.metric("📅 Réservations", len(df_reel))
    c4.metric("🌙 Nuits louées", label_nuits)
    c5.metric("📈 Revenu / nuit", f"{revenu_nuit:.0f} €")

    c6, c7, c8 = st.columns(3)
    frais_cb_total = float(df_reel["frais_cb"].fillna(0).sum()) if "frais_cb" in df_reel.columns else 0
    c6.metric("⏳ En attente", f"{kpis['montant_en_attente']:,.0f} €")
    c7.metric("🏡 Taux occupation", f"{taux_corrige:.1f} %")
    c8.metric("🔖 Commissions", f"{kpis['commissions']:,.0f} €")

    c9, c10 = st.columns(2)
    c9.metric("💳 Frais CB", f"{frais_cb_total:,.0f} €",
              help="Total des frais carte bancaire sur la période")
    ca_net_apres_cb = (kpis['ca_net'] - frais_cb_total) if frais_cb_total else kpis['ca_net']
    c10.metric("💵 CA Net (après CB)", f"{ca_net_apres_cb:,.0f} €",
               delta=f"-{frais_cb_total:,.0f} €" if frais_cb_total else None,
               delta_color="inverse")

    st.divider()

    col_left, col_right = st.columns(2)
    with col_left:
        st.subheader("📆 CA mensuel")
        monthly = compute_monthly(df)
        if not monthly.empty:
            fig = px.bar(monthly, x="mois_str", y="ca_net",
                         labels={"mois_str": "Mois", "ca_net": "CA Net (€)"},
                         color_discrete_sequence=["#2196F3"])
            fig.update_layout(height=300, margin=dict(t=20, b=20))
            st.plotly_chart(fig, use_container_width=True)

    with col_right:
        st.subheader("🏷️ Répartition plateformes")
        if kpis["repartition_plateformes"]:
            fig2 = px.pie(
                names=list(kpis["repartition_plateformes"].keys()),
                values=list(kpis["repartition_plateformes"].values()),
                color_discrete_sequence=px.colors.qualitative.Set2)
            fig2.update_layout(height=300, margin=dict(t=20, b=20))
            st.plotly_chart(fig2, use_container_width=True)

    st.divider()

    col_a, col_b = st.columns(2)
    with col_a:
        st.subheader("🔔 Arrivées dans 3 jours")
        arrivees = upcoming_arrivals(df)
        if arrivees.empty:
            st.info("Aucune arrivée imminente")
        else:
            st.dataframe(arrivees[["nom_client", "date_arrivee", "plateforme", "nuitees"]],
                         use_container_width=True, hide_index=True)

    with col_b:
        st.subheader("⚠️ Paiements en attente")
        non_payes = unpaid_reservations(df)
        if non_payes.empty:
            st.success("Tous les séjours sont payés ✅")
        else:
            st.dataframe(non_payes[["nom_client", "date_arrivee", "prix_net", "plateforme"]],
                         use_container_width=True, hide_index=True)

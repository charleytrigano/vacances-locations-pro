import streamlit as st
import plotly.express as px
from services.reservation_service import load_reservations
from services.analytics_service import compute_kpis, compute_monthly
from services.alert_service import upcoming_arrivals, unpaid_reservations
from database.supabase_client import is_connected, get_supabase
from services.proprietes_service import get_proprietes_dict, filter_df, get_propriete_selectionnee





def show():
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
    # Filtre propriété depuis la sidebar (session_state)
    prop_choix = get_propriete_selectionnee()
    props = get_proprietes_dict()

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

    # ── KPIs ──────────────────────────────────────────────────────────────
    c1, c2, c3, c4, c5 = st.columns(5)
    c1.metric("💰 CA Brut",        f"{kpis['ca_brut']:,.0f} €")
    c2.metric("💵 CA Net",          f"{kpis['ca_net']:,.0f} €")
    c3.metric("📅 Réservations",    kpis["nb_reservations"])
    c4.metric("🌙 Nuits totales",   kpis["nuits_total"])
    c5.metric("📈 Revenu / nuit",   f"{kpis['revenu_nuit']:.0f} €")

    c6, c7, c8 = st.columns(3)
    c6.metric("⏳ En attente",      f"{kpis['montant_en_attente']:,.0f} €")
    c7.metric("🏡 Taux occupation", f"{kpis['taux_occupation']} %")
    c8.metric("🔖 Commissions",     f"{kpis['commissions']:,.0f} €")

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

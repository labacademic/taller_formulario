# app.py
# Ejecuta: streamlit run app.py
import uuid
import pandas as pd
import streamlit as st

st.set_page_config(page_title="Riesgo de Crédito", page_icon="💳")

from utils_model import cargar_modelo, banda_riesgo, enviar_email_simple

st.title("💳 Formulario de Crédito — Evaluación de Riesgo")

# Modelo cacheado
@st.cache_resource
def _modelo():
    return cargar_modelo("modelo_credito.joblib")

modelo = _modelo()

# Entradas
c1, c2, c3 = st.columns(3)
salario = c1.number_input("Salario mensual (S/)", min_value=1000.0, max_value=8000.0, value=4000.0, step=100.0)
monto   = c2.number_input("Monto del préstamo (S/)", min_value=2000.0, max_value=10000.0, value=3000.0, step=100.0)
plazo   = c3.number_input("Plazo (meses)", min_value=6, max_value=36, value=12, step=1)

# Estado simple para recordar el último cálculo
if "ultimo" not in st.session_state:
    st.session_state.ultimo = None  # guardará dict con salario, monto, plazo, prob, nivel

if st.button("Calcular riesgo"):
    X = pd.DataFrame([{"salario": salario, "monto": monto, "plazo": plazo}])
    prob = float(modelo.predict_proba(X)[0, 1])
    nivel = banda_riesgo(prob)
    st.session_state.ultimo = {
        "salario": salario, "monto": monto, "plazo": plazo, "prob": prob, "nivel": nivel
    }

# Si hay un cálculo previo, muéstralo y permite correo
if st.session_state.ultimo:
    u = st.session_state.ultimo
    st.metric("Probabilidad de default", f"{u['prob']*100:.1f}%")
    st.write(f"Nivel de riesgo: **{u['nivel']}**")

    st.subheader("📧 Recibir confirmación por correo")
    deshabilitar_envio = (u["nivel"] == "Alto")
    if deshabilitar_envio:
        st.info("Para casos de riesgo **Alto**, no enviamos confirmación por correo.")

    # Form para evitar perder el submit por rerender
    with st.form("form_envio"):
        email = st.text_input("Tu correo electrónico", value="")
        enviar = st.form_submit_button("Enviar correo", disabled=deshabilitar_envio)

    if enviar:
        if not email.strip():
            st.error("Por favor, coloca un correo válido.")
        else:
            envio_id = str(uuid.uuid4())[:8]
            cuerpo = (
                "🎉 ¡Gracias por participar en el taller de hoy!\n\n"
                "Como agradecimiento, obtienes un **descuento especial** en el curso Machine Learning con Python.\n\n"
                "Detalles de tu simulación:\n"
                f"- Salario mensual: S/ {u['salario']:,.2f}\n"
                f"- Monto del préstamo: S/ {u['monto']:,.2f}\n"
                f"- Plazo: {u['plazo']} meses\n\n"
                "Resultado del modelo:\n"
                f"- Probabilidad estimada de default: {u['prob']*100:.1f}%\n"
                f"- Nivel de riesgo: {u['nivel']}\n\n"
                f"ID de referencia: {envio_id}\n\n"
                "¡Felicitaciones y gracias por confiar en nosotros!"
            )

            with st.spinner("Enviando correo..."):
                ok, msg = enviar_email_simple(
                    destinatario=email,
                    asunto=f"Confirmación y descuento especial — Formulario de Crédito (ID {envio_id})",
                    cuerpo_texto=cuerpo
                )

            if ok:
                st.success(f"✅ Correo enviado (ID {envio_id}). Revisa tu bandeja de entrada/spam.")
                st.toast("Correo enviado ✅", icon="✅")
            else:
                st.error(f"❌ No se pudo enviar el correo (ID {envio_id}). Detalle: {msg}")
                st.toast("Fallo al enviar correo ❌", icon="❌")

import streamlit as st


def show_auth_ui(supabase):
    st.subheader("Sign in to BOM Risk Checker")

    auth_mode = st.radio(
        "Choose an option",
        ["Login", "Create Account"],
        horizontal=True,
    )

    email = st.text_input("Email")
    password = st.text_input("Password", type="password")

    if auth_mode == "Create Account":
        if st.button("Create Account"):
            try:
                response = supabase.auth.sign_up(
                    {
                        "email": email,
                        "password": password,
                    }
                )

                st.success("Account created. Please check your email if confirmation is required.")
                st.session_state["user"] = response.user
                st.rerun()
                
            except Exception as error:
                st.error(f"Signup failed: {error}")

    else:
        if st.button("Login"):
            try:
                response = supabase.auth.sign_in_with_password(
                    {
                        "email": email,
                        "password": password,
                    }
                )

                st.success("Logged in successfully.")
                st.session_state["user"] = response.user
                st.rerun()

            except Exception as error:
                st.error(f"Login failed: {error}")
package com.example.mobileapp.ui.auth

import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.text.KeyboardActions
import androidx.compose.foundation.text.KeyboardOptions
import androidx.compose.foundation.verticalScroll
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.Email
import androidx.compose.material.icons.filled.Lock
import androidx.compose.material.icons.filled.Warning
import androidx.compose.material3.Button
import androidx.compose.material3.CircularProgressIndicator
import androidx.compose.material3.Icon
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.Surface
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.rememberCoroutineScope
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.platform.LocalSoftwareKeyboardController
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.input.ImeAction
import androidx.compose.ui.text.input.KeyboardType
import androidx.compose.ui.text.input.PasswordVisualTransformation
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.unit.dp
import cafe.adriel.voyager.core.screen.Screen
import cafe.adriel.voyager.navigator.LocalNavigator
import cafe.adriel.voyager.navigator.currentOrThrow
import com.example.mobileapp.core.auth.AuthSession
import com.example.mobileapp.core.auth.SupabaseAuthClient
import com.example.mobileapp.core.data.local.UserProfileRepository
import com.example.mobileapp.ui.main.MainHubScreen
import kotlinx.coroutines.launch
import org.koin.compose.koinInject

/**
 * M11 (F-04) — the sign-in screen.
 *
 * This replaces the previous "Login as Guest" stub, which navigated straight to
 * the hub without authenticating. That was only ever viable because the backend
 * accepted anonymous requests as a fixed development user; now that every
 * `/api/v1` route requires a verified token, a guest session would reach a
 * server that answers 401 to everything.
 *
 * The screen deliberately has no sign-up form: accounts are created in the
 * Supabase dashboard by the operator, so this app can only ever sign in to an
 * account that already exists. Offering a "create account" button that had
 * nowhere to post would be worse than not having one.
 */
class LoginScreen : Screen {

    @Composable
    override fun Content() {
        val navigator = LocalNavigator.currentOrThrow
        val authSession = koinInject<AuthSession>()
        val userProfileRepository = koinInject<UserProfileRepository>()
        val coroutineScope = rememberCoroutineScope()
        val keyboard = LocalSoftwareKeyboardController.current

        var email by remember { mutableStateOf("") }
        var password by remember { mutableStateOf("") }
        var error by remember { mutableStateOf<String?>(null) }
        var submitting by remember { mutableStateOf(false) }

        fun submit() {
            if (submitting) return
            if (email.isBlank() || password.isEmpty()) {
                error = "Enter your email and password."
                return
            }
            keyboard?.hide()
            error = null
            submitting = true
            coroutineScope.launch {
                val outcome = authSession.signIn(email, password)
                submitting = false
                when (outcome) {
                    is SupabaseAuthClient.Outcome.Success -> {
                        // Same routing rule the cold start uses, so a first-time
                        // user still sees onboarding and a returning one lands
                        // straight on the hub.
                        val profile = userProfileRepository.getProfile()
                        val destination =
                            if (profile.isOnboardingCompleted) MainHubScreen()
                            else OnboardingScreen()
                        navigator.replaceAll(destination)
                    }
                    SupabaseAuthClient.Outcome.InvalidCredentials ->
                        error = "Incorrect email or password."
                    SupabaseAuthClient.Outcome.NetworkError ->
                        error = "Can't reach FitQuest. Check your connection and try again."
                    SupabaseAuthClient.Outcome.NotConfigured ->
                        error = "This build has no Supabase project configured. " +
                            "Set SUPABASE_URL and SUPABASE_ANON_KEY and rebuild."
                    is SupabaseAuthClient.Outcome.ServerError ->
                        error = "FitQuest is having trouble signing you in (error " +
                            "${outcome.status}). Try again in a moment."
                    SupabaseAuthClient.Outcome.MalformedResponse ->
                        error = "Unexpected response from the sign-in service. Try again."
                }
            }
        }

        Surface(
            modifier = Modifier.fillMaxSize(),
            color = MaterialTheme.colorScheme.background
        ) {
            Column(
                modifier = Modifier
                    .fillMaxSize()
                    .verticalScroll(rememberScrollState())
                    .padding(horizontal = 24.dp, vertical = 32.dp),
                horizontalAlignment = Alignment.CenterHorizontally,
                verticalArrangement = Arrangement.Center
            ) {
                Text(
                    text = "FitQuest",
                    style = MaterialTheme.typography.headlineLarge,
                    fontWeight = FontWeight.Bold,
                    color = MaterialTheme.colorScheme.onBackground
                )
                Spacer(modifier = Modifier.height(8.dp))
                Text(
                    text = "Sign in to sync your runs and defend your territory.",
                    style = MaterialTheme.typography.bodyMedium,
                    color = MaterialTheme.colorScheme.onSurfaceVariant,
                    textAlign = TextAlign.Center
                )

                Spacer(modifier = Modifier.height(32.dp))

                OutlinedTextField(
                    value = email,
                    onValueChange = { email = it; error = null },
                    label = { Text("Email") },
                    singleLine = true,
                    enabled = !submitting,
                    leadingIcon = { Icon(Icons.Filled.Email, contentDescription = null) },
                    keyboardOptions = KeyboardOptions(
                        keyboardType = KeyboardType.Email,
                        imeAction = ImeAction.Next,
                    ),
                    modifier = Modifier.fillMaxWidth()
                )

                Spacer(modifier = Modifier.height(16.dp))

                OutlinedTextField(
                    value = password,
                    onValueChange = { password = it; error = null },
                    label = { Text("Password") },
                    singleLine = true,
                    enabled = !submitting,
                    leadingIcon = { Icon(Icons.Filled.Lock, contentDescription = null) },
                    visualTransformation = PasswordVisualTransformation(),
                    keyboardOptions = KeyboardOptions(
                        keyboardType = KeyboardType.Password,
                        imeAction = ImeAction.Done,
                    ),
                    keyboardActions = KeyboardActions(onDone = { submit() }),
                    modifier = Modifier.fillMaxWidth()
                )

                // Reserve the row whether or not there is an error, so the
                // button does not jump up and down as messages appear.
                Spacer(modifier = Modifier.height(16.dp))
                if (error != null) {
                    Row(
                        modifier = Modifier.fillMaxWidth(),
                        verticalAlignment = Alignment.Top,
                        horizontalArrangement = Arrangement.Start
                    ) {
                        Icon(
                            imageVector = Icons.Filled.Warning,
                            contentDescription = null,
                            tint = MaterialTheme.colorScheme.error,
                            modifier = Modifier.size(18.dp)
                        )
                        Spacer(modifier = Modifier.size(8.dp))
                        Text(
                            text = error.orEmpty(),
                            style = MaterialTheme.typography.bodySmall,
                            color = MaterialTheme.colorScheme.error
                        )
                    }
                    Spacer(modifier = Modifier.height(16.dp))
                }

                Button(
                    onClick = { submit() },
                    enabled = !submitting,
                    modifier = Modifier.fillMaxWidth()
                ) {
                    if (submitting) {
                        CircularProgressIndicator(
                            modifier = Modifier.size(18.dp),
                            strokeWidth = 2.dp,
                            color = MaterialTheme.colorScheme.onPrimary
                        )
                        Spacer(modifier = Modifier.size(12.dp))
                    }
                    Text(if (submitting) "Signing in…" else "Sign in")
                }
            }
        }
    }
}

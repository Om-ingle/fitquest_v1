package com.example.mobileapp.core.auth

import kotlinx.coroutines.flow.Flow

/**
 * "Who is signed in right now", as a value the data layer can read.
 *
 * ### Why this is an interface and not just [AuthSession]
 *
 * Everything below the network layer — Room entities, DAOs, repositories and
 * the process-lifetime caches — needs the current account in order to scope
 * what it reads and writes. Declaring that need as a one-method interface keeps
 * the dependency pointing in one direction (`data -> identity`) and keeps the
 * scoping logic testable without a Supabase client, a token store or a network.
 *
 * ### What the value is
 *
 * The Supabase Auth user id — the `sub` claim of the user's access token, and
 * the same value the backend resolves to an internal `user.id`
 * (`AuthTokens.userId`). It is therefore the ONE identifier that means the same
 * account on the device and on the server, which is what makes local data
 * attributable to a server-side identity rather than to "whoever used this
 * phone last".
 *
 * ### Two shapes, deliberately
 *
 * [currentSubject] is the synchronous read, for the write paths and for the
 * one-shot queries a UI makes while rendering. It answers from the session's
 * already-published state, so it is correct from the moment the process starts
 * — before `restore()` has had a chance to run — because the token store is
 * read synchronously when the session is constructed.
 *
 * [subject] is the observable form, used by the repositories' query flows. It
 * emits `null` while signed out and re-emits on every account change, which is
 * what lets a Room observer stop watching the previous account's rows: the
 * repository re-subscribes the DAO query against the new value instead of
 * continuing to collect a stream that was opened for someone else.
 */
interface IdentityProvider {

    /**
     * The signed-in account's subject, or `null` when no session exists.
     *
     * Callers must handle `null` explicitly. It does not mean "the default
     * user" — there is no default user. It means there is nobody to attribute
     * the operation to, and the correct response is to refuse it rather than to
     * write an unowned row.
     */
    fun currentSubject(): String?

    /** [currentSubject] as a flow: `null` while signed out, new value per account. */
    val subject: Flow<String?>
}

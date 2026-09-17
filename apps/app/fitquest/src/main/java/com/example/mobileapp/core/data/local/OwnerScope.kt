package com.example.mobileapp.core.data.local

import com.example.mobileapp.core.auth.IdentityProvider
import kotlinx.coroutines.ExperimentalCoroutinesApi
import kotlinx.coroutines.flow.Flow
import kotlinx.coroutines.flow.flatMapLatest
import kotlinx.coroutines.flow.flowOf

/**
 * The owner recorded on rows that predate local ownership (MIGRATION_5_6).
 *
 * Every table in the local database is scoped by `ownerSubject`, so a row
 * written before that column existed has no account to belong to. Rather than
 * delete those rows, or guess an account for them, the migration writes this
 * sentinel: the data stays in the file, intact and inspectable, and is simply
 * not visible to any account. See `FitQuestDatabase.MIGRATION_5_6` for the
 * policy and for how to re-assign it deliberately.
 *
 * It is also the constructor default for [RunSessionEntity] and friends, so
 * that entities built outside the data layer do not have to know the current
 * account. Every repository write stamps the real subject over it, and
 * `OwnerScopedQueryTest` fails if a query ever forgets its filter — so a row
 * still carrying this value after a write is a bug, not a state.
 */
const val LEGACY_UNOWNED_SUBJECT = "__legacy_unowned__"

/**
 * One log tag for every refusal to touch local data without an owner.
 *
 * A write that cannot name an owner is dropped rather than filed under a
 * placeholder, so this tag is how that shows up: `adb logcat -s FitQuestOwner`
 * answers "did anything get thrown away because nobody was signed in".
 */
internal const val OWNER_LOG_TAG = "FitQuestOwner"

/** The message logged when the data layer refuses an operation with no account. */
internal fun ownerlessRefusal(repository: String, action: String): String =
    "$repository.$action skipped: no authenticated subject. Local data is scoped " +
        "per account, so there is nobody to attribute this to and nothing was written."

/**
 * An account-scoped observer.
 *
 * [query] is the DAO's own flow for one account. The returned flow re-subscribes
 * it whenever [IdentityProvider.subject] changes, which is the part that matters
 * for privacy: a bare `dao.observeAll(owner)` collected by a long-lived screen
 * would keep emitting the rows it was opened for even after the account changed,
 * because the DAO only captured the owner it was given. `flatMapLatest` cancels
 * that subscription at the moment the subject changes and opens a fresh one for
 * the new account, so the previous account's rows cannot be delivered to the new
 * one.
 *
 * While signed out there is no account to query for, so the flow emits [empty]
 * and never touches the database. That is why the empty value has to be supplied
 * by the caller: `null` for a single-row observer, `emptyList()` for a list.
 */
@OptIn(ExperimentalCoroutinesApi::class)
internal fun <T> IdentityProvider.ownedFlow(
    empty: T,
    query: (ownerSubject: String) -> Flow<T>,
): Flow<T> = subject.flatMapLatest { owner ->
    if (owner == null) flowOf(empty) else query(owner)
}

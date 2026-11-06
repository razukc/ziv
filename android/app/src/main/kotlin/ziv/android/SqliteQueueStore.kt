/**
 * The held queue in SQLite: one row, the whole snapshot (held entries and
 * `last_acked`), replaced in one transaction, so a crash mid-write leaves the previous
 * snapshot intact and a process restart says hello with exactly what it still holds.
 * Held entries carry the words of messages not yet played — the queue, not a history;
 * a played entry is removed in the same write that records its id as acknowledged.
 */
package ziv.android

import android.content.ContentValues
import android.content.Context
import android.database.sqlite.SQLiteDatabase
import android.database.sqlite.SQLiteOpenHelper
import android.util.Log
import kotlinx.serialization.json.Json
import ziv.core.QueueSnapshot
import ziv.core.QueueStore

class SqliteQueueStore(context: Context) : SQLiteOpenHelper(context, "ziv-queue.db", null, 1), QueueStore {
    override val kind = "sqlite"
    private val json = Json { ignoreUnknownKeys = true; encodeDefaults = true }

    override fun onCreate(db: SQLiteDatabase) {
        db.execSQL("CREATE TABLE state (key TEXT PRIMARY KEY NOT NULL, value TEXT NOT NULL)")
    }

    override fun onUpgrade(db: SQLiteDatabase, oldVersion: Int, newVersion: Int) = Unit

    override fun load(): QueueSnapshot {
        readableDatabase.query("state", arrayOf("value"), "key = ?", arrayOf(KEY), null, null, null).use { c ->
            if (!c.moveToFirst()) return QueueSnapshot()
            return try {
                json.decodeFromString(QueueSnapshot.serializer(), c.getString(0))
            } catch (e: Exception) {
                Log.w(RendererService.TAG, "queue snapshot unreadable; starting empty: ${e.javaClass.simpleName}")
                QueueSnapshot()
            }
        }
    }

    override fun save(snap: QueueSnapshot) {
        val db = writableDatabase
        db.beginTransaction()
        try {
            val values = ContentValues().apply {
                put("key", KEY)
                put("value", json.encodeToString(QueueSnapshot.serializer(), snap))
            }
            db.insertWithOnConflict("state", null, values, SQLiteDatabase.CONFLICT_REPLACE)
            db.setTransactionSuccessful()
        } finally {
            db.endTransaction()
        }
    }

    companion object {
        private const val KEY = "queue"
    }
}

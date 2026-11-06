/**
 * Compose-box normalisation, as an aid before the relay's own: letters are
 * lower-cased, digits are spelled out one by one, and anything else is refused
 * with the character named. The relay still normalises what it receives.
 */
package ziv.core

sealed interface ComposeResult {
    data class Ok(val words: List<String>) : ComposeResult
    data class Refused(val reason: String) : ComposeResult
}

object Words {
    private val DIGITS = listOf("zero", "one", "two", "three", "four", "five", "six", "seven", "eight", "nine")

    fun compose(text: String): ComposeResult {
        val words = ArrayList<String>()
        for (raw in text.trim().split(Regex("\\s+"))) {
            if (raw.isEmpty()) continue
            val cur = StringBuilder()
            for (ch in raw) {
                when (ch) {
                    in 'a'..'z' -> cur.append(ch)
                    in 'A'..'Z' -> cur.append(ch.lowercaseChar())
                    in '0'..'9' -> {
                        if (cur.isNotEmpty()) {
                            words.add(cur.toString())
                            cur.setLength(0)
                        }
                        words.add(DIGITS[ch - '0'])
                    }
                    else -> return ComposeResult.Refused("\"$ch\" has no cell: use letters a to z and digits only")
                }
            }
            if (cur.isNotEmpty()) words.add(cur.toString())
        }
        if (words.isEmpty()) return ComposeResult.Refused("type at least one word")
        if (words.size > MAX_WORDS) return ComposeResult.Refused("at most $MAX_WORDS words in one message")
        words.firstOrNull { it.length > MAX_WORD_LETTERS }?.let {
            return ComposeResult.Refused("\"$it\" is longer than $MAX_WORD_LETTERS letters")
        }
        return ComposeResult.Ok(words)
    }
}

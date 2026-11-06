// The conformance player's entry: flags, the spec found from the working directory
// upward, the exact JSONL the harness reads.
package ziv.core

import java.io.File
import kotlin.test.Test
import kotlin.test.assertEquals
import kotlin.test.assertFailsWith

class MainTest {
    @Test
    fun `the player prints the reference timeline for a golden on both profiles`() {
        val (name, raw) = Repo.goldens().first { it.first == "message_two_words" }
        for (profile in Spec.PROFILE_NAMES) {
            val out = Main.run(arrayOf("--profile", profile, "--pace", Repo.spec.cellGapDefaultMs.toString()), raw, Repo.root)
            assertEquals(Repo.expected(name, profile), out)
        }
    }

    @Test
    fun `the spec is found from a nested working directory or taken from --spec`() {
        val (_, raw) = Repo.goldens().first()
        val nested = File(Repo.root, "android/core")
        val a = Main.run(arrayOf("--profile=six_actuator"), raw, nested)
        val b = Main.run(arrayOf("--spec", Repo.specFile.path, "--profile", "six_actuator"), raw, File("/"))
        assertEquals(a, b)
        assertFailsWith<IllegalArgumentException> { Main.run(arrayOf("--profile", "six_actuator"), raw, File("/")) }
    }

    @Test
    fun `bad flags fail loudly`() {
        assertFailsWith<IllegalArgumentException> { Main.parseArgs(arrayOf("--profile", "band")) }
        assertFailsWith<IllegalArgumentException> { Main.parseArgs(arrayOf("--pace", "slow")) }
        assertFailsWith<IllegalArgumentException> { Main.parseArgs(arrayOf("--pace")) }
        assertEquals(250, Main.parseArgs(arrayOf("--pace=250")).pace)
    }
}

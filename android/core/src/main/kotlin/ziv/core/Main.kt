/**
 * The conformance player: an utterance JSON on stdin, the timeline as JSON Lines on
 * stdout, one `{"t_ms","dot_mask","buzz_ms","label"}` per line, so
 * `conformance/run.py --player "android/core/build/install/core/bin/core"` can diff
 * this renderer's sequencer against the reference (conformance/README.md).
 *
 *   --profile <name>   six_actuator | single_actuator (default: single_actuator)
 *   --pace <ms>        cell gap (default: the spec's cell_gap_default_ms)
 *   --spec <path>      the timing spec (default: docs/haptic-timing.json, found from the
 *                      working directory upward — the harness runs from the repo root)
 *
 * Exit codes: 0 a timeline was printed; 1 bad arguments, no spec or an invalid utterance.
 */
package ziv.core

import java.io.File
import kotlin.system.exitProcess

object Main {
    class Args(var spec: String? = null, var profile: String = "single_actuator", var pace: Int? = null)

    fun parseArgs(argv: Array<String>): Args {
        val out = Args()
        var i = 0
        while (i < argv.size) {
            val a = argv[i]
            val eq = a.indexOf('=')
            val flag = if (eq >= 0) a.substring(0, eq) else a
            val inline = if (eq >= 0) a.substring(eq + 1) else null
            fun value(): String {
                if (inline != null) return inline
                i += 1
                return argv.getOrNull(i) ?: throw IllegalArgumentException("$flag needs a value")
            }
            when (flag) {
                "--spec" -> out.spec = value()
                "--profile" -> {
                    val p = value()
                    if (p !in Spec.PROFILE_NAMES) throw IllegalArgumentException("unknown profile $p")
                    out.profile = p
                }
                "--pace" -> out.pace = value().toIntOrNull() ?: throw IllegalArgumentException("--pace needs an integer")
                else -> System.err.println("core: ignoring unknown argument $a")
            }
            i += 1
        }
        return out
    }

    /** `docs/haptic-timing.json` in the working directory or any parent of it. */
    fun findSpec(from: File): File? {
        var dir: File? = from.absoluteFile
        while (dir != null) {
            val candidate = File(dir, "docs/haptic-timing.json")
            if (candidate.isFile) return candidate
            dir = dir.parentFile
        }
        return null
    }

    fun run(argv: Array<String>, stdin: String, cwd: File = File(".")): String {
        val args = parseArgs(argv)
        val specFile = args.spec?.let(::File)
            ?: findSpec(cwd)
            ?: throw IllegalArgumentException("no docs/haptic-timing.json above ${cwd.absolutePath}; pass --spec <path>")
        val spec = Spec.parse(specFile.readText())
        val utt = Wire.decodeUtterance(stdin)
        val pace = args.pace ?: spec.cellGapDefaultMs
        return Sequencer.toJsonl(Sequencer.timeline(utt, spec, pace, args.profile))
    }
}

fun main(argv: Array<String>) {
    try {
        val out = Main.run(argv, System.`in`.bufferedReader().readText())
        print(out)
        System.out.flush()
    } catch (e: Exception) {
        System.err.println("core: ${e.message ?: e.toString()}")
        exitProcess(1)
    }
}

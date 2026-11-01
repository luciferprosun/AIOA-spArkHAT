package eu.sparkhat.aioa.companion

/** Pure lifecycle rule shared by the ViewModel and JVM contract tests. */
data class Freshness(val generation: Long = 0, val state: String = "STALE", val validUntilElapsedMs: Long = 0) {
    fun invalidate(reason: String = "STALE") = Freshness(generation+1,reason)
    fun accept(epoch: Long, until: Long, now: Long = elapsedMs()): Freshness =
        if (epoch == generation && until > now) copy(state="FRESH",validUntilElapsedMs=until) else this
    fun isFresh(now: Long = elapsedMs()) = state == "FRESH" && now < validUntilElapsedMs
    fun canStop(taskState: String, now: Long = elapsedMs()) = isFresh(now) && taskState in setOf(
        "PREVIEWED","RUNNING","LIVE_PENDING_AUTHORIZATION","AGENT_PENDING","AGENT_APPROVED","AGENT_RUNNING")
    companion object { fun elapsedMs() = System.nanoTime()/1_000_000 }
}

/** Local opaque hints only: this never changes/resolves a Core operation. */
object PendingHints {
    fun archive(proposal: String, history: List<String>): List<String> {
        require(Wire.hex32.matches(proposal) && history.all { Wire.hex32.matches(it) })
        val result = (history+proposal).distinct()
        require(result.size <= 128)
        return result
    }
}

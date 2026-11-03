package eu.sparkhat.aioa.companion

import kotlinx.serialization.json.*

/** Only decoded after the existing client verifies the signed observation. */
data class ChatView(val requestId:String,val threadId:String,val state:String,val prompt:String?,val reply:String?,
    val requestDigest:String,val sourceSha:String,val receipt:JsonObject?,val error:String?,val live:Boolean) {
    companion object {
        fun decode(data:JsonObject,device:String,expectedId:String?=null):ChatView {
            require(Wire.text(data,"schema")=="aioa.mobile.chat-result.v1" && !Wire.flag(data,"save_knowledge"))
            val id=Wire.text(data,"request_id");val thread=Wire.text(data,"thread_id")
            require(Wire.hex32.matches(id) && Wire.hex32.matches(thread) && (expectedId==null || expectedId==id))
            require(Wire.text(data,"device_id")==device && Wire.text(data,"task_id")=="chat-$id")
            for(key in listOf("task_digest","request_digest","capsule_digest"))require(Wire.hex64.matches(Wire.text(data,key)))
            val source=Wire.text(data,"source_sha");require(Wire.sha40.matches(source))
            require(Wire.text(data,"provider_id")=="meta_model_api" && Wire.text(data,"model_id")=="muse-spark-1.3")
            val state=Wire.text(data,"state");require(state in setOf("PENDING_OWNER","RUNNING","SUCCEEDED","FAILED","UNKNOWN","STOPPED"))
            fun optional(key:String,limit:Int):String? {
                val item=data[key];if(item==null || item==JsonNull)return null
                val value=item.jsonPrimitive.content;require(value.toByteArray(Charsets.UTF_8).size<=limit);return value
            }
            val prompt=optional("prompt",2000);val reply=optional("reply",8192)
            val receipt=data["receipt"]?.takeUnless {it==JsonNull}?.jsonObject
            val live=Wire.flag(data,"live_verified")
            if(state=="SUCCEEDED") {
                require(live && receipt!=null && Wire.flag(receipt,"live_verified") && !Wire.flag(receipt,"fallback"))
                require(Wire.text(receipt,"schema")=="aioa.meta.chat-receipt.v1" &&
                    Wire.text(receipt,"environment")=="META_API_LIVE_VERIFIED" &&
                    Wire.text(receipt,"authority")=="ADVISORY_TEXT_ONLY" &&
                    Wire.text(receipt,"request_digest")==Wire.text(data,"request_digest"))
                val binding=receipt.getValue("binding").jsonObject
                for(key in listOf("device_id","request_id","thread_id","task_id","task_digest","source_sha","capsule_digest"))
                    require(Wire.text(binding,key)==Wire.text(data,key))
                require(Wire.hex64.matches(Wire.text(receipt,"response_sha256")))
                if(reply!=null)require(Wire.sha(reply.toByteArray(Charsets.UTF_8))==Wire.text(receipt,"response_sha256"))
                val usage=receipt.getValue("usage").jsonObject
                require(Wire.integer(usage,"prompt_tokens")>=0 && Wire.integer(usage,"completion_tokens") in 0..512 &&
                    Wire.integer(usage,"total_tokens")==Wire.integer(usage,"prompt_tokens")+Wire.integer(usage,"completion_tokens"))
            } else require(!live && receipt==null)
            return ChatView(id,thread,state,prompt,reply,Wire.text(data,"request_digest"),source,receipt,optional("error",128),live)
        }
    }
}

/** A pending ID is a readback hint, never a stored prompt or retry permission. */
data class ChatReadTarget(val kind:String,val id:String) {
    init {require(kind in setOf("REQUEST","THREAD") && Wire.hex32.matches(id))}
}
data class ChatUi(val threadId:String?=null,val pendingId:String?=null,val messages:List<ChatView> = emptyList(),
    val state:String="IDLE",val error:String?=null,val lastSignedAt:Long?=null) {
    val readbackOnly get()=pendingId!=null
    fun canSend(session:Boolean,capability:Boolean,busy:Boolean,draft:String)=session && capability && !busy &&
        pendingId==null && draft.isNotBlank() && draft.toByteArray(Charsets.UTF_8).size in 1..2000
    fun start(id:String):ChatUi {require(Wire.hex32.matches(id) && pendingId==null);return copy(pendingId=id,state="SENDING",error=null)}
    fun uncertain(code:String="CHAT_ACK_UNKNOWN")=copy(state="UNKNOWN",error=code)
    fun readbackPlan():List<ChatReadTarget> = buildList {
        pendingId?.let {add(ChatReadTarget("REQUEST",it))}
        threadId?.let {add(ChatReadTarget("THREAD",it))}
    }
    fun acceptThread(views:List<ChatView>,at:Long):ChatUi {
        require(views.size<=20 && views.all {it.threadId==threadId})
        for(view in views)messages.find {it.requestId==view.requestId}?.let {require(it.requestDigest==view.requestDigest)}
        val exact=pendingId?.let {id->views.find {it.requestId==id}}
        val pending=if(exact!=null && exact.state in setOf("SUCCEEDED","FAILED","STOPPED")) null else pendingId
        return copy(messages=views,pendingId=pending,lastSignedAt=at,
            state=if(pending!=null) exact?.state ?: state else views.lastOrNull()?.state ?: "IDLE",error=exact?.error)
    }
    fun accept(view:ChatView,at:Long):ChatUi {
        require(pendingId==null || pendingId==view.requestId)
        val pending=view.state in setOf("PENDING_OWNER","RUNNING","UNKNOWN")
        return copy(threadId=view.threadId,pendingId=if(pending)view.requestId else null,
            messages=(messages.filterNot {it.requestId==view.requestId}+view).takeLast(20),state=view.state,error=view.error,lastSignedAt=at)
    }
}

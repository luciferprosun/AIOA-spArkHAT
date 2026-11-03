package eu.sparkhat.aioa.companion

import android.content.Context
import android.net.ConnectivityManager
import android.net.Network
import android.net.NetworkCapabilities

/** Connectivity is only a wakeup hint. Host TLS/proofs establish actual reachability. */
internal class RecoveryNetworkMonitor(context: Context, private val changed: (Boolean) -> Unit) {
    private val manager = context.getSystemService(ConnectivityManager::class.java)
    private val state = RecoveryConnectivity(manager?.activeNetwork != null,manager?.activeNetwork?.networkHandle)
    @Volatile var available = state.available
        private set
    private var registered = false
    private val callback = object : ConnectivityManager.NetworkCallback() {
        override fun onCapabilitiesChanged(network: Network, capabilities: NetworkCapabilities) {
            update(capabilities.hasCapability(NetworkCapabilities.NET_CAPABILITY_INTERNET),network.networkHandle)
        }
        override fun onLost(network: Network) {
            synchronized(state) { if (state.identity == network.networkHandle) update(false,null) }
        }
    }
    private fun update(value: Boolean, identity: Long?) {
        synchronized(state) {
            if (state.update(value,identity)) { available=value; changed(value) }
        }
    }
    init {
        try { manager?.registerDefaultNetworkCallback(callback); registered=manager != null }
        catch (_: SecurityException) { available=false }
    }
    fun close() {
        if (registered) {
            registered=false
            try { manager?.unregisterNetworkCallback(callback) } catch (_: IllegalArgumentException) { }
        }
    }
}

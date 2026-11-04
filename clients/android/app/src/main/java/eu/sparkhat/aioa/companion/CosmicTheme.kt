package eu.sparkhat.aioa.companion

import androidx.compose.foundation.layout.*
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material3.*
import androidx.compose.runtime.Composable
import androidx.compose.ui.Modifier
import androidx.compose.ui.res.colorResource
import androidx.compose.ui.text.TextStyle
import androidx.compose.ui.text.font.Font
import androidx.compose.ui.text.font.FontFamily
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp

/** Local OFL fonts and shared generated resources. Never downloads at runtime. */
@Composable
internal fun CosmicTheme(content: @Composable () -> Unit) {
    val background=colorResource(R.color.cosmic_background)
    val surface=colorResource(R.color.cosmic_surface)
    val text=colorResource(R.color.cosmic_text)
    val muted=colorResource(R.color.cosmic_muted)
    val heading=FontFamily(Font(R.font.cosmic_space_grotesk))
    val body=FontFamily(Font(R.font.cosmic_manrope))
    val code=FontFamily(Font(R.font.cosmic_ibm_plex_mono))
    MaterialTheme(
        colorScheme=darkColorScheme(background=background,surface=surface,surfaceVariant=surface,
            primary=colorResource(R.color.cosmic_primary),onPrimary=background,
            secondary=colorResource(R.color.cosmic_secondary),onSecondary=background,
            tertiary=colorResource(R.color.cosmic_warning),onTertiary=background,
            error=colorResource(R.color.cosmic_danger),onError=background,
            onBackground=text,onSurface=text,onSurfaceVariant=muted,outline=muted),
        typography=Typography(
            headlineLarge=TextStyle(fontFamily=heading,fontWeight=FontWeight.Bold,fontSize=32.sp,lineHeight=40.sp),
            headlineMedium=TextStyle(fontFamily=heading,fontWeight=FontWeight.Bold,fontSize=28.sp,lineHeight=36.sp),
            headlineSmall=TextStyle(fontFamily=heading,fontWeight=FontWeight.Medium,fontSize=24.sp,lineHeight=32.sp),
            titleLarge=TextStyle(fontFamily=heading,fontWeight=FontWeight.Medium,fontSize=22.sp,lineHeight=30.sp),
            titleMedium=TextStyle(fontFamily=heading,fontWeight=FontWeight.Medium,fontSize=18.sp,lineHeight=26.sp),
            bodyLarge=TextStyle(fontFamily=body,fontSize=16.sp,lineHeight=24.sp),
            bodyMedium=TextStyle(fontFamily=body,fontSize=14.sp,lineHeight=20.sp),
            labelLarge=TextStyle(fontFamily=body,fontWeight=FontWeight.Bold,fontSize=14.sp,lineHeight=20.sp),
            labelSmall=TextStyle(fontFamily=code,fontSize=12.sp,lineHeight=18.sp)),
        content=content)
}

@Composable
internal fun CosmicCard(title: String, content: @Composable ColumnScope.() -> Unit) {
    Card(modifier=Modifier.fillMaxWidth(),shape=RoundedCornerShape(14.dp),
        colors=CardDefaults.cardColors(containerColor=MaterialTheme.colorScheme.surface)) {
        Column(Modifier.padding(16.dp),verticalArrangement=Arrangement.spacedBy(12.dp)) {
            Text(title,style=MaterialTheme.typography.titleMedium)
            content()
        }
    }
}

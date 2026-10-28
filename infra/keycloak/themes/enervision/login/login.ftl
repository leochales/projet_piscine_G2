<#--
  Page de connexion (maquette « Connexion – EnerVision ») : Card, Label, Input, Button et
  Alert de shadcn. Mêmes champs et même action que le login.ftl de base, sans ce que le
  realm n'utilise pas (inscription, fournisseurs d'identité, passkeys, « Se souvenir de
  moi », mot de passe oublié).
  Un courriel ou un mot de passe faux est une erreur des champs (messagesPerField), pas
  un message global : elle est affichée dans le même bloc Alert, en tête de carte.
-->
<#import "template.ftl" as layout>
<#assign credentialsError = messagesPerField.existsError('username','password')>
<@layout.registrationLayout displayMessage=!credentialsError; section>
    <#if section = "header">
        ${msg("loginAccountTitle")}
    <#elseif section = "subtitle">
        ${msg("enervisionLoginSubtitle")}
    <#elseif section = "form">
        <#if credentialsError>
            <@layout.alert type="error" id="input-error" text=kcSanitize(messagesPerField.getFirstError('username','password'))/>
        </#if>
        <form id="kc-form-login" class="${properties.kcFormClass!}" onsubmit="login.disabled = true; return true;" action="${url.loginAction}" method="post" novalidate>
            <#-- Absent quand Keycloak redemande seulement le mot de passe (le compte est
                 alors affiché en tête de carte par template.ftl) -->
            <#if !usernameHidden??>
                <div class="${properties.kcFormGroupClass!}">
                    <label for="username" class="${properties.kcLabelClass!}">${msg("email")}</label>
                    <input id="username" class="${properties.kcInputClass!}" name="username" value="${(login.username!'')}"
                           type="email" autofocus autocomplete="username" dir="ltr"
                           <#if credentialsError>aria-invalid="true" aria-describedby="input-error"</#if>
                    />
                </div>
            </#if>

            <div class="${properties.kcFormGroupClass!}">
                <label for="password" class="${properties.kcLabelClass!}">${msg("password")}</label>
                <div class="${properties.kcInputGroup!}" dir="ltr">
                    <input id="password" class="${properties.kcInputClass!}" name="password" type="password" autocomplete="current-password"
                           <#if usernameHidden??>autofocus</#if>
                           <#if credentialsError>aria-invalid="true" aria-describedby="input-error"</#if>
                    />
                    <button class="${properties.kcFormPasswordVisibilityButtonClass!}" type="button" aria-label="${msg("showPassword")}"
                            aria-controls="password" data-password-toggle
                            data-icon-show="${properties.kcFormPasswordVisibilityIconShow!}" data-icon-hide="${properties.kcFormPasswordVisibilityIconHide!}"
                            data-label-show="${msg('showPassword')}" data-label-hide="${msg('hidePassword')}">
                        <i class="${properties.kcFormPasswordVisibilityIconShow!}" aria-hidden="true"></i>
                    </button>
                </div>
            </div>

            <input type="hidden" id="id-hidden-input" name="credentialId" <#if auth.selectedCredential?has_content>value="${auth.selectedCredential}"</#if>/>
            <button class="${properties.kcButtonClass!} ${properties.kcButtonPrimaryClass!} ${properties.kcButtonBlockClass!}" name="login" id="kc-login" type="submit">${msg("doLogIn")}</button>
        </form>
        <script type="module" src="${url.resourcesPath}/js/passwordVisibility.js"></script>
    </#if>
</@layout.registrationLayout>

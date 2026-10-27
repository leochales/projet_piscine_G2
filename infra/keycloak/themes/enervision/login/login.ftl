<#--
  Page de connexion (maquette « Connexion – EnerVision ») : Card, Label, Input, Button et
  Alert de shadcn. Mêmes champs, même action et mêmes scripts que le login.ftl de base.
  Un identifiant ou un mot de passe faux est une erreur des champs (messagesPerField),
  pas un message global : elle est affichée dans le même bloc Alert, en tête de carte.
-->
<#import "template.ftl" as layout>
<#import "passkeys.ftl" as passkeys>
<#assign credentialsError = messagesPerField.existsError('username','password')>
<@layout.registrationLayout displayMessage=!credentialsError displayInfo=realm.password && realm.registrationAllowed && !registrationDisabled??; section>
    <#if section = "header">
        ${msg("loginAccountTitle")}
    <#elseif section = "subtitle">
        ${msg("enervisionLoginSubtitle")}
    <#elseif section = "form">
        <#if credentialsError>
            <@layout.alert type="error" id="input-error" text=kcSanitize(messagesPerField.getFirstError('username','password'))/>
        </#if>
        <div id="kc-form">
            <#if realm.password>
                <form id="kc-form-login" class="${properties.kcFormClass!}" onsubmit="login.disabled = true; return true;" action="${url.loginAction}" method="post" novalidate>
                    <#if !usernameHidden??>
                        <div class="${properties.kcFormGroupClass!}">
                            <label for="username" class="${properties.kcLabelClass!}"><#if !realm.loginWithEmailAllowed>${msg("username")}<#elseif !realm.registrationEmailAsUsername>${msg("usernameOrEmail")}<#else>${msg("email")}</#if></label>
                            <input id="username" class="${properties.kcInputClass!}" name="username" value="${(login.username!'')}"
                                   type="<#if realm.loginWithEmailAllowed && realm.registrationEmailAsUsername>email<#else>text</#if>"
                                   autofocus autocomplete="${(enableWebAuthnConditionalUI?has_content)?then('username webauthn', 'username')}"
                                   <#if credentialsError>aria-invalid="true" aria-describedby="input-error"</#if>
                                   dir="ltr"
                            />
                        </div>
                    </#if>

                    <div class="${properties.kcFormGroupClass!}">
                        <div class="ev-label-row">
                            <label for="password" class="${properties.kcLabelClass!}">${msg("password")}</label>
                            <#if realm.resetPasswordAllowed>
                                <a href="${url.loginResetCredentialsUrl}" class="ev-link ev-link-muted">${msg("doForgotPassword")}</a>
                            </#if>
                        </div>
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

                    <#if realm.rememberMe && !usernameHidden??>
                        <div class="${properties.kcCheckClass!}">
                            <input id="rememberMe" class="${properties.kcCheckInputClass!}" name="rememberMe" type="checkbox"<#if login.rememberMe??> checked</#if>>
                            <label for="rememberMe" class="${properties.kcCheckLabelClass!}">${msg("rememberMe")}</label>
                        </div>
                    </#if>

                    <input type="hidden" id="id-hidden-input" name="credentialId" <#if auth.selectedCredential?has_content>value="${auth.selectedCredential}"</#if>/>
                    <button class="${properties.kcButtonClass!} ${properties.kcButtonPrimaryClass!} ${properties.kcButtonBlockClass!}" name="login" id="kc-login" type="submit">${msg("doLogIn")}</button>
                </form>
            </#if>
        </div>
        <@passkeys.conditionalUIData />
        <script type="module" src="${url.resourcesPath}/js/passwordVisibility.js"></script>
    <#elseif section = "info">
        <#if realm.password && realm.registrationAllowed && !registrationDisabled??>
            <div id="kc-registration">
                <span>${msg("noAccount")} <a class="ev-link" href="${url.registrationUrl}">${msg("doRegister")}</a></span>
            </div>
        </#if>
    <#elseif section = "socialProviders">
        <#if realm.password && social?? && social.providers?has_content>
            <div id="kc-social-providers" class="ev-social">
                <p class="ev-separator"><span>${msg("identity-provider-login-label")}</span></p>
                <ul>
                    <#list social.providers as p>
                        <li>
                            <a data-once-link data-disabled-class="ev-disabled" id="social-${p.alias}"
                               class="${properties.kcButtonClass!} ${properties.kcButtonDefaultClass!} ${properties.kcButtonBlockClass!}" href="${p.loginUrl}">${p.displayName!}</a>
                        </li>
                    </#list>
                </ul>
            </div>
        </#if>
    </#if>
</@layout.registrationLayout>

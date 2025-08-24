package com.locationapp.auth.dto;

public class AuthResponse {
    private String accessToken;
    private String refreshToken;
    private Long userId;
    private String username;

    public AuthResponse() {}

    public AuthResponse(String accessToken, String refreshToken, Long userId, String username) {
        this.accessToken = accessToken;
        this.refreshToken = refreshToken;
        this.userId = userId;
        this.username = username;
    }

    // getters & setters
    public String getAccessToken() { return accessToken; }
    public void setAccessToken(String accessToken) { this.accessToken = accessToken; }

    public String getRefreshToken() { return refreshToken; }
    public void setRefreshToken(String refreshToken) { this.refreshToken = refreshToken; }

    public Long getUserId() { return userId; }
    public void setUserId(Long userId) { this.userId = userId; }

    public String getUsername() { return username; }
    public void setUsername(String username) { this.username = username; }
}

package com.locationapp.auth.dto;

import com.locationapp.auth.entity.User;
import java.time.LocalDateTime;
import java.util.Set;

public class UserProfileResponse {
    private Long id;
    private String username;
    private String email;
    private String firstName;
    private String lastName;
    private String phoneNumber;
    private Set<User.Role> roles;
    private LocalDateTime createdAt;
    private LocalDateTime lastLogin;

    public UserProfileResponse() {}

    public UserProfileResponse(Long id, String username, String email, String firstName,
                               String lastName, String phoneNumber, Set<User.Role> roles,
                               LocalDateTime createdAt, LocalDateTime lastLogin) {
        this.id = id;
        this.username = username;
        this.email = email;
        this.firstName = firstName;
        this.lastName = lastName;
        this.phoneNumber = phoneNumber;
        this.roles = roles;
        this.createdAt = createdAt;
        this.lastLogin = lastLogin;
    }

    // getters & setters (omitted here for brevity — add them similarly)
    public Long getId() { return id; }
    public void setId(Long id) { this.id = id; }
    public String getUsername() { return username; }
    public void setUsername(String username) { this.username = username; }
    public String getEmail() { return email; }
    public void setEmail(String email) { this.email = email; }
    public String getFirstName() { return firstName; }
    public void setFirstName(String firstName) { this.firstName = firstName; }
    public String getLastName() { return lastName; }
    public void setLastName(String lastName) { this.lastName = lastName; }
    public String getPhoneNumber() { return phoneNumber; }
    public void setPhoneNumber(String phoneNumber) { this.phoneNumber = phoneNumber; }
    public Set<User.Role> getRoles() { return roles; }
    public void setRoles(Set<User.Role> roles) { this.roles = roles; }
    public LocalDateTime getCreatedAt() { return createdAt; }
    public void setCreatedAt(LocalDateTime createdAt) { this.createdAt = createdAt; }
    public LocalDateTime getLastLogin() { return lastLogin; }
    public void setLastLogin(LocalDateTime lastLogin) { this.lastLogin = lastLogin; }
}
